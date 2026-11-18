"""Power and camera fault episodes built from eligible observation history."""

import json
from itertools import takewhile

from .asset_context import DeviceContext
from .config import RulesConfig
from .fault import FaultDecision
from .individual_faults import plan_changes, plan_timeline
from .models import LikelyCause, WhoActs
from .projection import DeviceFacts, project_device
from .store import EventFact
from .time_utils import from_epoch_us, utc_text


_US_PER_SECOND = 1_000_000
_BLOCKED_PLANS = {"paused", "ended"}


def _observed(event: EventFact) -> int:
    assert event.observed_us is not None
    return event.observed_us


def _evidence(*events: EventFact | None) -> tuple[EventFact, ...]:
    return tuple(dict.fromkeys(event for event in events if event is not None))


def power_fault(at_us: int, context: DeviceContext, rules: RulesConfig) -> FaultDecision | None:
    facts = context.facts
    disconnect = facts.power_disconnect
    if context.device.family != "T" or disconnect is None:
        return None

    opening = last_disconnect = None
    for event in facts.observations:
        if event.kind == "power_disconnect":
            opening = opening or event
            last_disconnect = event
        elif event.kind == "power_restore" and last_disconnect is not None:
            if _observed(event) > _observed(last_disconnect):
                opening = last_disconnect = None
    assert opening is not None

    backup = next(
        (
            event for event in reversed(facts.observations)
            if _observed(event) >= _observed(opening)
            and event.kind == "low_voltage"
            and json.loads(event.payload_json).get("source") == "backup_battery"
        ),
        None,
    )
    latest = facts.freshest_measurement
    reason = (
        f"The tracker reported an external-power disconnect at {utc_text(from_epoch_us(_observed(disconnect)))}. "
        "External power restoration remains unverified."
    )
    if backup is not None:
        reason += f" It reported low backup-battery voltage at {utc_text(from_epoch_us(_observed(backup)))}."
    if latest is not None and facts.ignition_on is not None:
        deadline = (
            rules.calibrated_parameters.tracker_driving_overdue.value
            if facts.ignition_on else rules.given_rules.tracker_parked_overdue.value
        )
        if at_us - _observed(latest) > deadline * _US_PER_SECOND:
            reason += " Device reports are now overdue."
        elif _observed(latest) > _observed(opening):
            reason += " Device messages have continued since the disconnect."

    return FaultDecision(
        cause=LikelyCause.POWER_LOSS,
        reason=reason,
        evidence=_evidence(opening, disconnect, backup, latest, facts.ignition_evidence),
        owner=WhoActs.TECHNICIAN,
        next_action="Inspect the tracker harness and restore external power.",
        opened_us=_observed(opening),
    )


def _storage_episode_opening(facts: DeviceFacts) -> EventFact | None:
    if facts.camera_storage_error is None:
        return None
    opening = last_error = None
    for event in facts.observations:
        if event.kind != "camera_status":
            continue
        status = json.loads(event.payload_json).get("status")
        if status == "storage_error":
            opening = opening or event
            last_error = event
        elif status == "recording" and last_error is not None and _observed(event) > _observed(last_error):
            opening = last_error = None
    return opening


def _same_asset_since(history: tuple[EventFact, ...], start_us: int, expected_vin: str | None) -> bool:
    if expected_vin is None:
        return True
    previous_claim_us = None
    previous_vins = set()
    for event in history:
        if event.kind not in {"ignition_on", "heartbeat"}:
            continue
        vin = json.loads(event.payload_json).get("vin")
        if not vin:
            continue
        observed = _observed(event)
        if observed > start_us:
            if vin != expected_vin:
                return False
        else:
            if observed != previous_claim_us:
                previous_vins.clear()
                previous_claim_us = observed
            previous_vins.add(vin)
    return not previous_vins or previous_vins == {expected_vin}


def _inferred_opening(
    at_us: int, context: DeviceContext, rules: RulesConfig
) -> tuple[int, tuple[EventFact, ...]] | None:
    facts = context.facts
    tracker = context.tracker_facts
    if (
        facts.camera_evidence is None
        or context.tracker_ambiguous
        or tracker is None
        or tracker.ignition_on is not True
        or tracker.ignition_since is None
        or tracker.ignition_evidence is None
        or tracker.power_disconnect is not None
    ):
        return None

    plan = plan_timeline(facts.observations)
    if plan.opening is not None:
        return None
    resume = plan.last_resumption

    ignition = tracker.ignition_evidence
    drive_window = rules.calibrated_parameters.tracker_driving_overdue.value * _US_PER_SECOND
    if at_us - _observed(ignition) > drive_window:
        return None

    since = tracker.ignition_since
    expected_vin = context.asset.vin if context.asset is not None else None
    if not _same_asset_since(tracker.observations, _observed(since), expected_vin):
        return None
    anchor = since
    if resume is not None and _observed(resume) > _observed(anchor):
        anchor = resume
    if _observed(facts.camera_evidence) > _observed(anchor):
        # Anchor the deadline to recording, even if the latest status is booting.
        recording = next(
            (
                event for event in reversed(facts.observations)
                if event.kind == "camera_status"
                and _observed(event) > _observed(anchor)
                and json.loads(event.payload_json).get("status") == "recording"
            ),
            None,
        )
        if recording is not None:
            anchor = recording

    recording_due = _observed(anchor) + rules.calibrated_parameters.camera_recording_overdue.value * _US_PER_SECOND
    wake_due = _observed(since) + rules.operational_assumptions.camera_wake_grace.value * _US_PER_SECOND
    opening = max(recording_due, wake_due)
    if at_us <= opening:
        return None
    return opening, _evidence(anchor, since)


def _plan_usable_through(observations: tuple[EventFact, ...], start_us: int, end_us: int) -> bool:
    blocked = set()
    for event, plan, status in plan_changes(observations):
        observed = _observed(event)
        if observed >= end_us:
            break
        if observed > start_us and (blocked or status in _BLOCKED_PLANS):
            return False
        if status in _BLOCKED_PLANS:
            blocked.add(plan)
        else:
            blocked.discard(plan)
    return not blocked


def _awake_through(
    tracker: DeviceFacts, attempt: EventFact, end_us: int, at_us: int, expected_vin: str | None
) -> EventFact | None:
    # Apply the query's receipt cutoff and inspect physical ignition through
    # the trial interval. Backfilled off/on transitions can disprove continuity.
    history = tuple(takewhile(lambda event: _observed(event) < end_us, tracker.observations))
    end = project_device(at_us, history)
    mode = end.ignition_since
    if (
        end.ignition_on is True
        and mode is not None
        and _observed(mode) <= _observed(attempt)
        and mode.first_received_us <= attempt.first_received_us
        and end.power_disconnect is None
        and _same_asset_since(history, _observed(mode), expected_vin)
    ):
        return mode
    return None


def _reboot_checks(
    at_us: int,
    context: DeviceContext,
    opening_us: int,
    opening_facts: tuple[EventFact, ...],
    grace_seconds: int,
) -> tuple[list[tuple[EventFact, EventFact]], EventFact | None]:
    tracker = context.tracker_facts
    failed = []
    pending = None
    if tracker is None or context.tracker_ambiguous:
        return failed, pending

    commands = context.facts.reboot_commands
    expected_vin = context.asset.vin if context.asset is not None else None
    opening_receipt = max(event.first_received_us for event in opening_facts)
    for index, command in enumerate(commands):
        issued = _observed(command)
        if issued <= opening_us or command.first_received_us < opening_receipt:
            continue
        deadline = issued + grace_seconds * _US_PER_SECOND
        if index + 1 < len(commands) and _observed(commands[index + 1]) < deadline:
            continue
        end_us = min(deadline, at_us + 1)
        if not _plan_usable_through(context.facts.observations, issued, end_us):
            continue
        awake_mode = _awake_through(tracker, command, end_us, at_us, expected_vin)
        if awake_mode is None:
            continue
        if at_us >= deadline:
            failed.append((command, awake_mode))
        else:
            pending = command
    return failed, pending


def camera_fault(
    at_us: int, context: DeviceContext, rules: RulesConfig, *, allow_inferred: bool
) -> FaultDecision | None:
    if context.device.family != "C":
        return None
    facts = context.facts
    tracker = context.tracker_facts
    explicit = _storage_episode_opening(facts)
    if explicit is not None:
        opening_us, opening_facts = _observed(explicit), (explicit,)
        reason = (
            f"The camera reported a storage error at {utc_text(from_epoch_us(opening_us))}. "
            "Recording recovery remains unverified."
        )
    else:
        inferred = _inferred_opening(at_us, context, rules) if allow_inferred else None
        if inferred is None:
            return None
        opening_us, opening_facts = inferred
        reason = f"Tracker ignition is on and the camera's recording deadline passed at {utc_text(from_epoch_us(opening_us))}."

    policy = rules.operational_assumptions
    failed, pending = _reboot_checks(
        at_us, context, opening_us, opening_facts, policy.camera_reboot_response_grace.value
    )
    required = policy.camera_failed_reboots_before_visit.value
    failed_evidence = (event for pair in failed[-required:] for event in pair)
    ignition = tracker.ignition_evidence if tracker is not None and not context.tracker_ambiguous else None
    parked = ignition is not None and tracker.ignition_on is False
    recheck_us = None
    owner = WhoActs.SUPPORT
    if len(failed) >= required:
        owner = WhoActs.TECHNICIAN
        reason += f" Recording stayed unavailable through {len(failed)} complete awake reboot checks."
        next_action = "Inspect the camera storage and verify recording after repair."
    elif pending is not None:
        recheck_us = _observed(pending) + policy.camera_reboot_response_grace.value * _US_PER_SECOND
        reason += f" The current remote reboot response window ends at {utc_text(from_epoch_us(recheck_us))}."
        next_action = "Monitor the current remote reboot and verify recording by the end of its response window."
    elif plan_timeline(facts.observations).opening is not None:
        next_action = "Review the inactive connectivity plan and verify recording after service resumes."
    elif parked:
        reason += " The vehicle is parked."
        next_action = "Try a remote reboot at the next ignition-on and verify recording."
    else:
        next_action = "Attempt a remote reboot and verify recording while the vehicle is awake."

    return FaultDecision(
        cause=LikelyCause.CAMERA_FAULT,
        reason=reason,
        evidence=_evidence(
            *opening_facts, facts.camera_storage_error, facts.camera_evidence,
            ignition, *context.tracker_evidence, *failed_evidence, pending,
        ),
        owner=owner,
        next_action=next_action,
        confidence=1.0 if explicit is not None else 0.8,
        opened_us=opening_us,
        recheck_us=recheck_us,
    )
