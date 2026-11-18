"""Evaluate normal device timing from immutable as-of facts."""

import json
from dataclasses import dataclass
from datetime import datetime

from .asset_context import DeviceContext
from .config import RulesConfig
from .models import DeviceState, DeviceStatus, LikelyCause
from .projection import DeviceFacts
from .store import EventFact
from .time_utils import from_epoch_us, to_epoch_us


_US_PER_SECOND = 1_000_000


@dataclass(frozen=True, slots=True)
class _Decision:
    state: DeviceState
    cause: LikelyCause
    reason: str
    evidence: tuple[EventFact | None, ...]


def _unknown(reason: str, *evidence: EventFact | None) -> _Decision:
    return _Decision(DeviceState.UNKNOWN, LikelyCause.UNKNOWN, reason, evidence)


def _reporting(reason: str, *evidence: EventFact | None) -> _Decision:
    return _Decision(DeviceState.REPORTING, LikelyCause.NONE, reason, evidence)


def _duration(seconds: int) -> str:
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    parts = ((hours, "hour"), (minutes, "minute"), (seconds, "second"))
    return " ".join(f"{count} {unit}{'s' if count != 1 else ''}" for count, unit in parts if count) or "0 seconds"


def _observed(event: EventFact) -> int:
    assert event.observed_us is not None
    return event.observed_us


def _fresh(event: EventFact, at_us: int, seconds: int) -> bool:
    return 0 <= at_us - _observed(event) <= seconds * _US_PER_SECOND


def _tracker(at_us: int, facts: DeviceFacts, rules: RulesConfig) -> _Decision:
    if facts.power_disconnect is not None:
        return _unknown(
            "The tracker reported an external-power disconnect. Restoration is still unverified.",
            facts.power_disconnect,
            facts.freshest_measurement,
        )
    mode = facts.ignition_since
    if mode is None or facts.ignition_on is None:
        return _unknown("Tracker ignition is unverified. Its reporting mode is uncertain.", facts.freshest_measurement)

    ignition = (mode, facts.ignition_evidence)
    if facts.ignition_on:
        deadline = rules.calibrated_parameters.tracker_driving_overdue.value
        for event in reversed(facts.observations):
            if _observed(event) < _observed(mode):
                break
            if event.kind != "position" or json.loads(event.payload_json).get("ignition") is not True:
                continue
            if _fresh(event, at_us, deadline):
                return _reporting(
                    f"Ignition is on and a driving position was observed within {_duration(deadline)}.",
                    event,
                    *ignition,
                )
            return _unknown(
                f"Ignition is on and the last driving position is older than {_duration(deadline)}.",
                event,
                *ignition,
            )
        return _unknown("Ignition is on and a position for the current drive is still unavailable.", *ignition)

    deadline = rules.given_rules.tracker_parked_overdue.value
    latest = facts.freshest_measurement
    if latest is not None and _fresh(latest, at_us, deadline):
        return _Decision(
            DeviceState.QUIET_EXPECTED,
            LikelyCause.PARKED_NORMAL,
            f"Ignition is off and a tracker report was observed within the {_duration(deadline)} parked allowance.",
            (latest, *ignition),
        )
    return _unknown(
        f"Ignition is off and the last tracker observation is older than {_duration(deadline)}.",
        latest,
        *ignition,
    )


def _camera(at_us: int, context: DeviceContext, rules: RulesConfig) -> _Decision:
    facts = context.facts
    latest = facts.camera_evidence
    status = facts.camera_status
    if facts.camera_storage_error is not None:
        return _unknown(
            "The camera reported a storage error. Recording recovery is still unverified.",
            facts.camera_storage_error,
            latest,
        )
    if latest is None:
        return _unknown("A credible camera status observation is still unavailable.")

    deadline = rules.calibrated_parameters.camera_recording_overdue.value
    fresh = _fresh(latest, at_us, deadline)
    recording = status == "recording" and fresh
    tracker = context.tracker_facts
    if context.tracker_ambiguous or tracker is None or tracker.ignition_since is None or tracker.ignition_on is None:
        ignition_reason = (
            "Competing tracker claims leave same-asset ignition uncertain."
            if context.tracker_ambiguous else "Same-asset tracker ignition is unverified."
        )
        if recording:
            return _reporting(f"The camera sent a recent recording report. {ignition_reason}", latest)
        return _unknown(
            f"{ignition_reason} A current camera recording is unavailable.",
            latest,
            *context.tracker_evidence,
        )

    mode = tracker.ignition_since
    mode_us = _observed(mode)
    camera_us = _observed(latest)
    evidence = (latest, mode, tracker.ignition_evidence, *context.tracker_evidence)
    elapsed_us = at_us - mode_us
    if tracker.ignition_on:
        if recording and camera_us >= mode_us:
            return _reporting("The camera reported recording during the current ignition-on period.", *evidence)
        grace = rules.operational_assumptions.camera_wake_grace.value
        if elapsed_us <= grace * _US_PER_SECOND:
            return _unknown(
                f"The vehicle is within its {_duration(grace)} camera wake grace after ignition-on.",
                *evidence,
            )
        return _unknown(
            f"Ignition is on and a camera recording from this drive is overdue or older than {_duration(deadline)}.",
            *evidence,
        )

    sleep_delay = rules.given_rules.camera_sleep_delay.value
    sleep_us = mode_us + sleep_delay * _US_PER_SECOND
    if status == "sleeping" and camera_us >= mode_us:
        return _Decision(
            DeviceState.QUIET_EXPECTED,
            LikelyCause.SLEEPING_BY_DESIGN,
            "The camera reported sleeping after the vehicle switched ignition off.",
            evidence,
        )
    if at_us < sleep_us:
        if recording:
            return _reporting("The camera sent a recent recording during the post-ignition-off transition.", *evidence)
        return _unknown(
            f"The vehicle switched ignition off within {_duration(sleep_delay)}. The camera is in its sleep transition.",
            *evidence,
        )
    if fresh and camera_us >= sleep_us:
        if recording:
            return _reporting("The camera is still reporting recordings after the expected sleep time.", *evidence)
        return _unknown("The camera reported awake after its expected sleep time. Recording is unverified.", *evidence)
    return _Decision(
        DeviceState.QUIET_EXPECTED,
        LikelyCause.SLEEPING_BY_DESIGN,
        f"The vehicle has been off for at least {_duration(sleep_delay)} and the camera is quiet as designed.",
        evidence,
    )


def _battery_tag(at_us: int, facts: DeviceFacts, rules: RulesConfig) -> _Decision:
    latest = facts.battery_evidence
    if latest is None:
        return _unknown("A credible battery-tag check-in is still unavailable.")
    deadline = rules.calibrated_parameters.a_daily_overdue.value
    daily_interval = rules.given_rules.a_checkin_interval.value
    if _fresh(latest, at_us, deadline):
        return _reporting(f"The battery tag checked in within its {_duration(deadline)} daily reporting allowance.", latest)
    if _fresh(latest, at_us, deadline + daily_interval):
        return _unknown(f"The tag has missed one daily check-in beyond its {_duration(deadline)} allowance.", latest)
    return _unknown("The tag has gone more than one daily check-in opportunity without a report.", latest)


def evaluate_status(at: datetime, rules: RulesConfig, context: DeviceContext) -> DeviceStatus:
    """Use observation time for freshness and first-receipt time for last contact."""
    at_us = to_epoch_us(at)
    facts = context.facts
    contact = facts.last_contact
    family = context.device.family
    if family == "BX":
        decision = _unknown("No decoded BX observations are available at the requested instant.")
    elif facts.freshest_measurement is None:
        if contact is None:
            decision = _unknown("No device observations are available at the requested instant.")
        elif contact.time_quality == "clock_ahead":
            decision = _unknown("The latest device receipt carries a clock ahead of platform receipt time.", contact)
        else:
            decision = _unknown("The latest device receipt describes a time after the requested instant.", contact)
    elif family == "T":
        decision = _tracker(at_us, facts, rules)
    elif family == "C":
        decision = _camera(at_us, context, rules)
    else:
        decision = _battery_tag(at_us, facts, rules)

    evidence = dict.fromkeys(
        event.event_id
        for event in (*decision.evidence, *context.assignment_evidence, contact)
        if event is not None
    )
    return DeviceStatus(
        serial=context.device.serial,
        asset_id=context.asset_id,
        at=at,
        state=decision.state,
        likely_cause=decision.cause,
        confidence=0.0 if decision.state == DeviceState.UNKNOWN else 1.0,
        last_heard_at=from_epoch_us(contact.first_received_us) if contact is not None else None,
        reasons=[decision.reason],
        evidence=list(evidence),
    )
