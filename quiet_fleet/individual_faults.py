"""Project individual account and battery episodes from eligible observations."""

import json
from collections.abc import Iterator
from dataclasses import dataclass

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


def low_a_battery(facts: DeviceFacts, rules: RulesConfig) -> FaultDecision | None:
    low = rules.operational_assumptions.a_low_battery.value
    recovery = rules.operational_assumptions.a_battery_recovery.value
    opening: EventFact | None = None
    last_low: EventFact | None = None
    for event in facts.observations:
        if event.kind != "check_in":
            continue
        percent = json.loads(event.payload_json)["battery_pct"]
        if percent <= low:
            opening = opening or event
            last_low = event
        elif last_low is not None and percent >= recovery and event.observed_us > last_low.observed_us:
            opening = last_low = None
    if opening is None or last_low is None:
        return None

    last_low_percent = json.loads(last_low.payload_json)["battery_pct"]
    evidence = (opening, last_low)
    if facts.battery_evidence is not None:
        evidence += (facts.battery_evidence,)
    return FaultDecision(
        cause=LikelyCause.BATTERY_LOW,
        reason=(
            f"The tag reported {last_low_percent:g}% battery at {utc_text(from_epoch_us(last_low.observed_us))}. "
            f"Its latest reading is {facts.battery_pct:g}% and a later reading of at least {recovery:g}% is required for recovery."
        ),
        evidence=evidence,
        owner=WhoActs.TECHNICIAN,
        next_action="Inspect and replace the depleted battery or tag as needed.",
        opened_us=opening.observed_us,
    )
