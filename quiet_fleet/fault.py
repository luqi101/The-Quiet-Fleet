"""A cause and its evidence-backed recommendation for the shared evaluator."""

from collections.abc import Iterable
from dataclasses import dataclass
from itertools import groupby

from .models import DeviceState, LikelyCause, WhoActs
from .store import EventFact


@dataclass(frozen=True, slots=True)
class FaultDecision:
    cause: LikelyCause
    reason: str
    evidence: tuple[EventFact, ...]
    owner: WhoActs
    next_action: str
    confidence: float = 1.0
    state: DeviceState = DeviceState.NEEDS_ACTION
    opened_us: int | None = None
    recheck_us: int | None = None


def active_episode(transitions: Iterable[tuple[EventFact, bool]]) -> tuple[EventFact | None, EventFact | None]:
    """Find the opening and latest fault in observation order. True means fault."""
    opening = latest = None
    for _, simultaneous in groupby(transitions, key=lambda transition: transition[0].observed_us):
        first_fault = last_fault = None
        for event, is_fault in simultaneous:
            if is_fault:
                first_fault = first_fault or event
                last_fault = event
        if first_fault is None:
            opening = latest = None
        else:
            # Recovery needs a strictly later observation than the latest fault.
            opening = opening or first_fault
            latest = last_fault
    return opening, latest


def owned_action(owner: WhoActs, step: str) -> str:
    role = "a technician" if owner == WhoActs.TECHNICIAN else owner.value
    return f"Ask {role} to {step[0].lower() + step[1:]}"
