"""Project individual account and battery episodes from eligible observations."""

import json

from .config import RulesConfig
from .fault import FaultDecision
from .models import LikelyCause, WhoActs
from .projection import DeviceFacts
from .store import EventFact


def inactive_plan(facts: DeviceFacts) -> FaultDecision | None:
    current = {}
    for event in reversed(facts.observations):
        if event.kind != "plan_change":
            continue
        payload = json.loads(event.payload_json)
        current.setdefault(payload["plan"], (payload["status"], event))
    inactive = [(plan, status, event) for plan, (status, event) in current.items() if status != "active"]
    if not inactive:
        return None
    labels = ", ".join(f"{plan} ({status})" for plan, status, _ in inactive)
    return FaultDecision(
        cause=LikelyCause.PLAN_PAUSED,
        reason=f"The latest effective changes leave connectivity plans inactive ({labels}).",
        evidence=tuple(event for _, _, event in inactive),
        owner=WhoActs.SUPPORT,
        next_action="Verify the account plan and obtain approval for reactivation if service is needed.",
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
            f"The tag reported {last_low_percent:g}% battery during the current episode. "
            f"Its latest reading is {facts.battery_pct:g}% and a later reading of at least {recovery:g}% is required for recovery."
        ),
        evidence=evidence,
        owner=WhoActs.TECHNICIAN,
        next_action="Inspect and replace the depleted battery or tag as needed.",
    )
