"""Resolve asset and tracker hypotheses from a single as-of telemetry view."""

import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime

from .config import RulesConfig
from .projection import DeviceFacts, project_device
from .reference import Device, References
from .store import EventFact, EventStore, ReadSnapshot
from .time_utils import from_epoch_us


@dataclass(frozen=True, slots=True)
class DeviceContext:
    device: Device
    facts: DeviceFacts
    asset_id: str | None
    assignment_evidence: tuple[EventFact, ...] = ()
    tracker_facts: DeviceFacts | None = None
    tracker_evidence: tuple[EventFact, ...] = ()
    tracker_ambiguous: bool = False


@dataclass(frozen=True, slots=True)
class _Assignment:
    asset_id: str | None
    evidence: tuple[EventFact, ...] = ()
    competing_assets: frozenset[str] = frozenset()


@dataclass(frozen=True, slots=True)
class _Tracker:
    device: Device
    assignment: _Assignment
    latest: EventFact


def _roster_asset(device: Device, at: datetime) -> str | None:
    installed = device.installed_at
    if isinstance(installed, datetime):
        return device.asset_id if installed <= at else None
    return device.asset_id if installed is None or installed <= at.date() else None


def _vin(event: EventFact) -> str:
    return json.loads(event.payload_json)["vin"]


def _latest_own_claims(facts: DeviceFacts) -> tuple[EventFact, ...]:
    claims = []
    for event in reversed(facts.observations):
        if claims and event.observed_us != claims[0].observed_us:
            break
        if event.kind in {"heartbeat", "ignition_on"}:
            claims.append(event)
    return tuple(reversed(claims))


def _assignment(
    device: Device, at: datetime, claims: tuple[EventFact, ...], assets_by_vin: dict[str, set[str]]
) -> _Assignment:
    roster = _roster_asset(device, at)
    vins = {_vin(event) for event in claims}
    observed_assets = {asset_id for vin in vins for asset_id in assets_by_vin.get(vin, ())}
    if len(vins) > 1 or len(observed_assets) > 1:
        return _Assignment(None, claims, frozenset(observed_assets | ({roster} if roster else set())))
    if observed_assets:
        return _Assignment(observed_assets.pop(), claims)
    return _Assignment(roster)


def _confirmed_handover(snapshot: ReadSnapshot, candidates: list[_Tracker]) -> list[_Tracker]:
    successors = [c for c in candidates if c.device.status == "active" and c.assignment.evidence]
    if len(successors) != 1:
        return candidates
    successor = successors[0]
    first_claim = snapshot.first_vin_claim(successor.device.serial, _vin(successor.assignment.evidence[0]))
    if first_claim is None or first_claim.observed_us is None:
        return candidates
    return [
        c for c in candidates
        if c.device.status != "removed" or c.latest.observed_us >= first_claim.observed_us
    ]


def _camera_tracker(
    snapshot: ReadSnapshot, references: References, asset_id: str, assets_by_vin: dict[str, set[str]],
    at: datetime, at_us: int, recent_us: int,
) -> tuple[tuple[EventFact, ...], tuple[EventFact, ...], bool]:
    claims = defaultdict(list)
    for event in snapshot.latest_vin_claims():
        claims[event.serial].append(event)

    candidates = []
    conflicts = []
    for device in references.devices.values():
        if device.family != "T":
            continue
        assignment = _assignment(device, at, tuple(claims[device.serial]), assets_by_vin)
        if asset_id in assignment.competing_assets:
            conflicts.extend(assignment.evidence)
        if assignment.asset_id != asset_id:
            continue
        latest = snapshot.latest_measurement(device.serial)
        if latest is not None:
            candidates.append(_Tracker(device, assignment, latest))

    candidates = _confirmed_handover(snapshot, candidates)
    recent = [candidate for candidate in candidates if at_us - candidate.latest.observed_us <= recent_us]
    plausible = recent or candidates
    verified = [candidate for candidate in plausible if candidate.assignment.evidence]
    contenders = verified or plausible
    if conflicts or len(contenders) > 1:
        evidence = tuple(conflicts) + tuple(
            event for candidate in contenders for event in (candidate.assignment.evidence or (candidate.latest,))
        )
        return (), evidence, True
    if not contenders:
        return (), (), False
    selected = contenders[0]
    return snapshot.facts_for(selected.device.serial), selected.assignment.evidence, False


def load_device_context(
    store: EventStore, references: References, device: Device, at_us: int, rules: RulesConfig
) -> DeviceContext:
    """Copy related receipts under one lock, with no wall-clock or schedule inference."""
    at = from_epoch_us(at_us)
    asset_id = _roster_asset(device, at)
    assets_by_vin: dict[str, set[str]] = defaultdict(set)
    if device.family in {"T", "C"}:
        for asset in references.assets.values():
            if asset.vin:
                assets_by_vin[asset.vin].add(asset.asset_id)

    tracker_events: tuple[EventFact, ...] = ()
    tracker_evidence: tuple[EventFact, ...] = ()
    ambiguous = False
    with store.read_snapshot(at_us) as snapshot:
        facts = project_device(at_us, snapshot.facts_for(device.serial))
        if device.family == "T":
            assignment = _assignment(device, at, _latest_own_claims(facts), assets_by_vin)
            return DeviceContext(device, facts, assignment.asset_id, assignment.evidence)
        if device.family == "C" and asset_id is not None and facts.camera_evidence is not None:
            tracker_events, tracker_evidence, ambiguous = _camera_tracker(
                snapshot, references, asset_id, assets_by_vin, at, at_us,
                rules.given_rules.tracker_parked_overdue.value * 1_000_000,
            )

    tracker_facts = project_device(at_us, tracker_events) if tracker_events else None
    return DeviceContext(
        device, facts, asset_id, tracker_facts=tracker_facts,
        tracker_evidence=tracker_evidence, tracker_ambiguous=ambiguous,
    )
