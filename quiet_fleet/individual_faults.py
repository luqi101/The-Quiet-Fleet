"""Project individual account and battery episodes from eligible observations."""

import json
from collections.abc import Iterator
from dataclasses import dataclass
from itertools import groupby

from .bx import BX_REPORT
from .config import RulesConfig
from .fault import FaultDecision, active_episode
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
    changes = (event for event in observations if event.kind == "plan_change")
    severity = {"active": 0, "paused": 1, "ended": 2}
    for _, simultaneous in groupby(changes, key=lambda event: event.observed_us):
        by_plan = {}
        for event in simultaneous:
            change = json.loads(event.payload_json)
            plan, status = change["plan"], change["status"]
            previous = by_plan.get(plan)
            if previous is None or severity[status] >= severity[previous[2]]:
                by_plan[plan] = event, plan, status
        # Across plans, apply new holds before removals at the same instant.
        yield from sorted(by_plan.values(), key=lambda change: change[2] == "active")


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

    payloads = ((event, json.loads(event.payload_json)) for event in facts.observations if event.kind == kind)
    readings = (
        (
            event,
            reading["battery_pct"],
            reading["low_battery"] if bx else reading["battery_pct"] <= policy.a_low_battery.value,
        )
        for event, reading in payloads
    )
    opening, last_low = active_episode((event, low) for event, percent, low in readings if low or percent >= recovery)
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
