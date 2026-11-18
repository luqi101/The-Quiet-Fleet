"""A cause and its evidence-backed recommendation for the shared evaluator."""

from dataclasses import dataclass

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


def owned_action(owner: WhoActs, step: str) -> str:
    role = "a technician" if owner == WhoActs.TECHNICIAN else owner.value
    return f"Ask {role} to {step[0].lower() + step[1:]}"
