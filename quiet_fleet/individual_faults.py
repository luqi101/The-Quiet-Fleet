"""Project individual account and battery episodes from eligible observations."""

import json
from collections.abc import Iterator
from dataclasses import dataclass

from .bx import BX_REPORT
from .config import RulesConfig
from .fault import FaultDecision
from .models import LikelyCause, WhoActs
from .projection import DeviceFacts
from .store import EventFact
from .time_utils import from_epoch_us, utc_text


@dataclass(frozen=True, slots=True)
class PlanState:
    inactive: tuple[tuple[str, str, EventFact], ...]
    opening: EventFact | None
    last_resumption: EventFact | None


def plan_changes(observations: tuple[EventFact, ...]) -> Iterator[tuple[EventFact, str, str]]:
    for event in observations:
        if event.kind == "plan_change":
            change = json.loads(event.payload_json)
            yield event, change["plan"], change["status"]


def plan_timeline(observations: tuple[EventFact, ...]) -> PlanState:
    blocked = {}
    opening = resumed = None
    for event, plan, status in plan_changes(observations):
        if status != "active":
            opening = opening or event
            blocked[plan] = (status, event)
        elif plan in blocked:
            del blocked[plan]
            if not blocked:
                opening = None
                resumed = event
    return PlanState(tuple((plan, status, event) for plan, (status, event) in sorted(blocked.items())), opening, resumed)


def inactive_plan(facts: DeviceFacts) -> FaultDecision | None:
    timeline = plan_timeline(facts.observations)
    if timeline.opening is None:
        return None
    labels = ", ".join(
        f"{plan} {status} effective {utc_text(from_epoch_us(event.observed_us))}"
        for plan, status, event in timeline.inactive
    )
    return FaultDecision(
        cause=LikelyCause.PLAN_PAUSED,
        reason=f"Connectivity plans remain inactive ({labels}). Service availability requires account confirmation.",
        evidence=tuple(dict.fromkeys((timeline.opening, *(event for _, _, event in timeline.inactive)))),
        owner=WhoActs.SUPPORT,
        next_action="Verify the account plan and obtain approval for reactivation if service is needed.",
        opened_us=timeline.opening.observed_us,
    )


def battery_fault(facts: DeviceFacts, family: str, rules: RulesConfig) -> FaultDecision | None:
    if family not in {"A", "BX"}:
        return None
    bx = family == "BX"
    kind = BX_REPORT if bx else "check_in"
    policy = rules.operational_assumptions
    recovery = policy.bx_battery_recovery.value if bx else policy.a_battery_recovery.value
    latest = facts.bx_report if bx else facts.battery_evidence
    if latest is None:
        return None

    readings = ((event, json.loads(event.payload_json)) for event in facts.observations if event.kind == kind)
    # At an equal BX clock, a clear cannot split an episode renewed by a low flag.
    if bx:
        readings = sorted(readings, key=lambda item: (item[0].observed_us, not item[1]["low_battery"]))
    opening = last_low = None
    for event, reading in readings:
        percent = reading["battery_pct"]
        low = reading["low_battery"] if bx else percent <= policy.a_low_battery.value
        if low:
            opening = opening or event
            last_low = event
        elif last_low is not None and percent >= recovery and event.observed_us > last_low.observed_us:
            opening = last_low = None
    if opening is None or last_low is None:
        return None

    low_pct = json.loads(last_low.payload_json)["battery_pct"]
    latest_reading = json.loads(latest.payload_json)
    observed = utc_text(from_epoch_us(last_low.observed_us))
    if bx:
        reason = (
            f"The BX low-battery flag was set at {observed} with an estimated charge of {low_pct:g}%. "
            f"Recovery needs a later report with a clear flag and at least {recovery:g}% estimated charge."
        )
        if not latest_reading["gps_fix"]:
            reason += " The latest BX report also lacks a valid GPS fix."
        step = "Inspect the BX tracker and replace its battery or the unit as needed."
    else:
        reason = (
            f"The tag reported {low_pct:g}% battery at {observed}. Its latest reading is {latest_reading['battery_pct']:g}% "
            f"and a later reading of at least {recovery:g}% is required for recovery."
        )
        step = "Inspect and replace the depleted battery or tag as needed."
    return FaultDecision(
        cause=LikelyCause.BATTERY_LOW,
        reason=reason,
        evidence=(opening, last_low, latest),
        owner=WhoActs.TECHNICIAN,
        next_action=step,
        opened_us=opening.observed_us,
    )
