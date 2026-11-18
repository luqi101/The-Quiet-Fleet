"""Evaluate bounded cold, approved downtime, and tracker coverage explanations."""

import json

from .asset_context import DeviceContext
from .config import RulesConfig
from .fault import FaultDecision
from .models import DeviceState, LikelyCause, WhoActs
from .store import EventFact
from .time_utils import DEPOT_ZONES, from_epoch_us, utc_text


_US_PER_SECOND = 1_000_000
_CONTEXT_CONFIDENCE = 0.65


def _observed(event: EventFact) -> int:
    assert event.observed_us is not None
    return event.observed_us


def cold_fault(at_us: int, context: DeviceContext, rules: RulesConfig) -> FaultDecision | None:
    """Use the depot's overnight low on the first overdue check-in's local date."""
    asset = context.asset
    latest = context.facts.battery_evidence
    battery_pct = context.facts.battery_pct
    policy = rules.operational_assumptions
    if context.device.family != "A" or asset is None or latest is None or battery_pct is None:
        return None
    if battery_pct < policy.cold_healthy_battery_minimum.value:
        return None

    observed_us = _observed(latest)
    overdue_us = observed_us + rules.calibrated_parameters.a_daily_overdue.value * _US_PER_SECOND
    cold_limit_us = policy.cold_silence_limit.value * _US_PER_SECOND
    if at_us <= overdue_us or at_us - observed_us > cold_limit_us:
        return None
    overdue_day = from_epoch_us(overdue_us).astimezone(DEPOT_ZONES[asset.depot]).date()
    weather = context.weather.get((asset.depot, overdue_day))
    if weather is None or weather.low_c > policy.cold_temperature.value:
        return None

    return FaultDecision(
        cause=LikelyCause.COLD_WEATHER,
        reason=(
            f"The tag missed its daily report after reading {battery_pct:g}% battery. "
            f"The {asset.depot} overnight low for {overdue_day} was {weather.low_c:g} °C, "
            "which supports temporary cold-weather quiet."
        ),
        evidence=(latest,),
        owner=WhoActs.NONE,
        next_action="Monitor for the next daily check-in within the cold-weather allowance.",
        confidence=_CONTEXT_CONFIDENCE,
        state=DeviceState.QUIET_EXPECTED,
    )


def downtime_fault(at_us: int, context: DeviceContext, rules: RulesConfig) -> FaultDecision | None:
    """Use authorized asset/depot scopes and half-open depot-local date windows."""
    asset = context.asset
    if asset is None or not rules.operational_assumptions.seasonal_downtime_suppression_enabled.value:
        return None

    try:
        day = from_epoch_us(at_us).astimezone(DEPOT_ZONES[asset.depot]).date()
    except OverflowError:
        return None
    for window in rules.site_policy.downtime:
        if window.depot is not None and window.depot != asset.depot:
            continue
        if asset.asset_id not in window.asset_ids and asset.use not in window.asset_uses:
            continue
        if not window.start_local <= day < window.end_local:
            continue
        latest = context.facts.freshest_measurement
        return FaultDecision(
            cause=LikelyCause.PLANNED_DOWNTIME,
            reason=(
                f"Approved downtime covers {asset.asset_id} in {asset.depot} on {day}. "
                f"The approved return date is {window.end_local}."
            ),
            evidence=(latest,) if latest is not None else (),
            owner=WhoActs.NONE,
            next_action="Verify normal reporting when the approved downtime ends.",
            state=DeviceState.QUIET_EXPECTED,
            )
    return None


def _weak_signal(context: DeviceContext, earliest_us: int, maximum: int) -> EventFact | None:
    for event in reversed(context.facts.observations):
        if _observed(event) < earliest_us:
            break
        if event.kind == "heartbeat":
            signal = json.loads(event.payload_json)["signal"]
            return event if signal <= maximum else None
    return None


def _receipt_order(event: EventFact) -> tuple[int, str]:
    return event.first_received_us, event.event_id


def coverage_fault(at_us: int, context: DeviceContext, rules: RulesConfig) -> FaultDecision | None:
    """Assess a currently overdue drive using contemporaneous and already-known evidence."""
    facts = context.facts
    if context.device.family != "T" or not facts.ignition_on or facts.ignition_since is None:
        return None
    mode_us = _observed(facts.ignition_since)
    positions = []
    for event in reversed(facts.observations):
        if _observed(event) < mode_us:
            break
        if event.kind == "position" and json.loads(event.payload_json)["ignition"] is True:
            positions.append(event)
    if not positions:
        return None

    latest = positions[0]
    latest_us = _observed(latest)
    age_us = at_us - latest_us
    due_us = rules.calibrated_parameters.tracker_driving_overdue.value * _US_PER_SECOND
    monitor_limit_us = rules.site_policy.coverage_monitor_limit.value * _US_PER_SECOND
    if not due_us < age_us <= monitor_limit_us:
        return None

    normal_lag = rules.calibrated_parameters.normal_receipt_lag.value
    position_interval = rules.given_rules.tracker_position_interval.value
    buffer_lag_us = (position_interval + normal_lag) * _US_PER_SECOND
    buffered = tuple(event for event in positions if event.first_received_us - _observed(event) > buffer_lag_us)
    signal = _weak_signal(context, latest_us - due_us, rules.site_policy.weak_signal_max.value)
    backfill = max(
        (event for event in buffered if at_us - event.first_received_us <= due_us),
        key=_receipt_order,
        default=None,
    )
    next_action = "Check connectivity and verify that a current position arrives."
    timely = next((event for event in positions if event.first_received_us <= _observed(event) + due_us), latest)
    opening = _observed(timely) + due_us
    observed = utc_text(from_epoch_us(latest_us))

    if backfill is not None:
        reason = (
            f"The platform received a buffered driving position at {utc_text(from_epoch_us(backfill.first_received_us))}. "
            f"The newest position was observed at {observed}. A live position is still overdue."
        )
        if signal is None:
            return FaultDecision(
                cause=LikelyCause.UNKNOWN,
                reason=reason,
                evidence=(backfill, latest),
                owner=WhoActs.NONE,
                next_action=next_action,
                confidence=0.0,
                state=DeviceState.UNKNOWN,
            )
        return FaultDecision(
            cause=LikelyCause.COVERAGE_GAP,
            reason=f"{reason} A recent weak signal supports a coverage gap.",
            evidence=(backfill, latest, signal),
            owner=WhoActs.SUPPORT,
            next_action=next_action,
            confidence=_CONTEXT_CONFIDENCE,
            opened_us=opening,
        )

    if signal is None:
        return None
    prior = max(
        (event for event in buffered if event.first_received_us <= latest_us),
        key=_receipt_order,
        default=None,
    )
    if prior is None or age_us > due_us + prior.first_received_us - _observed(prior):
        return None
    return FaultDecision(
        cause=LikelyCause.COVERAGE_GAP,
        reason=(
            f"The last driving position was observed at {observed} and an update is overdue. "
            "Recent weak signal and earlier buffered positions on this drive support a temporary coverage gap."
        ),
        evidence=(latest, signal, prior),
        owner=WhoActs.SUPPORT,
        next_action=next_action,
        confidence=_CONTEXT_CONFIDENCE,
        opened_us=opening,
    )
