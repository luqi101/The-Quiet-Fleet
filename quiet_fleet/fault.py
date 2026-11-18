"""A cause and its evidence-backed recommendation for the shared evaluator."""

from dataclasses import dataclass

from .models import DeviceState, LikelyCause, Priority, WhoActs
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
    priority: Priority = Priority.MEDIUM
