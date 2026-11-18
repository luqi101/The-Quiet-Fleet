"""Resolve asset and tracker hypotheses from a single as-of telemetry view."""

import json
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time
from types import MappingProxyType

from .config import RulesConfig
from .projection import DeviceFacts, project_device
from .reference import Asset, Device, References, Weather
from .store import EventFact, EventStore, ReadSnapshot
from .time_utils import from_epoch_us, to_epoch_us


@dataclass(frozen=True, slots=True)
class DeviceContext:
    device: Device
    facts: DeviceFacts
    asset_id: str | None
    assignment_evidence: tuple[EventFact, ...] = ()
    tracker_facts: DeviceFacts | None = None
    tracker_evidence: tuple[EventFact, ...] = ()
    tracker_ambiguous: bool = False
    asset: Asset | None = None
    weather: Mapping[tuple[str, date], Weather] = field(default_factory=lambda: MappingProxyType({}))
    assignment_ambiguous: bool = False
    documented_removed: bool = False


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

    @property
    def evidence(self) -> tuple[EventFact, ...]:
        return tuple(dict.fromkeys((*self.assignment.evidence, self.latest)))


def _installation(device: Device) -> datetime | None:
    installed = device.installed_at
    if installed is None or isinstance(installed, datetime):
        return installed
    return datetime.combine(installed, time.min, tzinfo=UTC)


def _roster_asset(device: Device, at: datetime) -> str | None:
    # A BX message identifies hardware but carries no asset or installation claim.
    if device.family == "BX" and device.status == "stock":
        return None
    installed = _installation(device)
    return device.asset_id if installed is None or installed <= at else None


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
    device: Device, at: datetime, claims: tuple[EventFact, ...], assets_by_vin: Mapping[str, set[str]]
) -> _Assignment:
    roster = _roster_asset(device, at)
    vins = {_vin(event) for event in claims}
    observed_assets = {asset_id for vin in vins for asset_id in assets_by_vin.get(vin, ())}
    if len(vins) > 1 or len(observed_assets) > 1:
        return _Assignment(None, claims, frozenset(observed_assets | ({roster} if roster else set())))
    if observed_assets:
        return _Assignment(observed_assets.pop(), claims)
    return _Assignment(roster)


def _trackers_on_asset(
    snapshot: ReadSnapshot, references: References, asset: Asset, roster_serials: tuple[str, ...],
    assets_by_vin: Mapping[str, set[str]], at: datetime,
) -> tuple[list[_Tracker], tuple[EventFact, ...]]:
    claims = defaultdict(list)
    for event in snapshot.related_vin_claims(asset.vin, roster_serials):
        claims[event.serial].append(event)

    candidates = []
    conflicts = []
    for serial in sorted(set(roster_serials) | claims.keys()):
        device = references.devices.get(serial)
        if device is None or device.family != "T":
            continue
        assignment = _assignment(device, at, tuple(claims[serial]), assets_by_vin)
        if asset.asset_id in assignment.competing_assets:
            conflicts.extend(assignment.evidence)
        if assignment.asset_id == asset.asset_id:
            latest = snapshot.latest_measurement(serial)
            if latest is not None:
                candidates.append(_Tracker(device, assignment, latest))
    return candidates, tuple(conflicts)


def _documented_removals(
    snapshot: ReadSnapshot, candidates: list[_Tracker], asset_id: str, at: datetime,
) -> dict[str, tuple[EventFact, ...]]:
    successors = [
        tracker for tracker in candidates
        if tracker.device.status == "active" and tracker.assignment.evidence
        and _roster_asset(tracker.device, at) == asset_id
    ]
    if len(successors) != 1 or not any(tracker.device.status == "removed" for tracker in candidates):
        return {}
    successor = successors[0]
    known_vin = _vin(successor.assignment.evidence[0])
    first_claim = snapshot.first_vin_claim(successor.device.serial, known_vin)
    if first_claim is None or first_claim.observed_us is None:
        return {}

    return {
        tracker.device.serial: (*tracker.evidence, first_claim)
        for tracker in candidates
        if tracker.device.status == "removed" and tracker.device.asset_id == asset_id
        and tracker.latest.observed_us < first_claim.observed_us
    }


def _recent_trackers(candidates: list[_Tracker], at_us: int, recent_us: int) -> list[_Tracker]:
    return [tracker for tracker in candidates if at_us - tracker.latest.observed_us <= recent_us]


class DeviceContextReader:
    """Reuse related VIN and tracker reads for one as-of view."""

    def __init__(self, snapshot: ReadSnapshot, references: References, rules: RulesConfig) -> None:
        self.snapshot = snapshot
        self.references = references
        self.at = from_epoch_us(snapshot.at_us)
        self.recent_us = rules.given_rules.tracker_parked_overdue.value * 1_000_000
        self.assets_by_vin: dict[str, set[str]] = defaultdict(set)
        tracker_roster = defaultdict(list)
        for asset in references.assets.values():
            if asset.vin:
                self.assets_by_vin[asset.vin].add(asset.asset_id)
        for device in references.devices.values():
            if device.family == "T" and device.asset_id is not None:
                tracker_roster[device.asset_id].append(device.serial)
        self.tracker_roster = {asset_id: tuple(serials) for asset_id, serials in tracker_roster.items()}

        self._cohort_facts: dict[str, DeviceFacts] = {}
        self._last_full_tracker: tuple[str, DeviceFacts] | None = None
        self._trackers: dict[str, tuple[list[_Tracker], tuple[EventFact, ...], dict[str, tuple[EventFact, ...]]]] = {}

    def _project(self, serial: str, *, cohort_tracker: bool = False) -> DeviceFacts:
        if not cohort_tracker:
            device = self.references.devices[serial]
            if self._last_full_tracker is not None and self._last_full_tracker[0] == serial:
                return self._last_full_tracker[1]
            installed = _installation(device) if device.family == "BX" else None
            facts = project_device(
                self.snapshot.at_us, self.snapshot.facts_for(serial),
                bx_installed_us=to_epoch_us(installed) if installed is not None else None,
            )
            if device.family == "T":
                # A paired camera can use the same immutable tracker history
                # without keeping every tracker in memory for the whole queue.
                self._last_full_tracker = serial, facts
            return facts
        if serial not in self._cohort_facts:
            self._cohort_facts[serial] = project_device(self.snapshot.at_us, self.snapshot.tracker_cohort_facts(serial))
        return self._cohort_facts[serial]

    def _asset_trackers(self, asset: Asset) -> tuple[
        list[_Tracker], tuple[EventFact, ...], dict[str, tuple[EventFact, ...]],
    ]:
        if asset.asset_id not in self._trackers:
            candidates, conflicts = _trackers_on_asset(
                self.snapshot, self.references, asset, self.tracker_roster.get(asset.asset_id, ()),
                self.assets_by_vin, self.at,
            )
            removals = _documented_removals(self.snapshot, candidates, asset.asset_id, self.at)
            self._trackers[asset.asset_id] = (
                [tracker for tracker in candidates if tracker.device.serial not in removals], conflicts, removals,
            )
        return self._trackers[asset.asset_id]

    def read(self, device: Device, *, cohort: bool = False) -> DeviceContext:
        # The slim view is used exclusively for incident eligibility. A device
        # diagnosis retains full history, including contact and coverage evidence.
        facts = None if cohort and device.family == "C" else self._project(device.serial, cohort_tracker=cohort)
        claims = _latest_own_claims(facts) if device.family == "T" else ()
        assignment = _assignment(device, self.at, claims, self.assets_by_vin)
        asset = self.references.assets.get(assignment.asset_id)
        assignment_evidence = assignment.evidence
        assignment_ambiguous = assignment.asset_id is None and bool(assignment_evidence)
        tracker_facts = None
        tracker_evidence: tuple[EventFact, ...] = ()
        tracker_ambiguous = documented_removed = False
        context_needed = (
            device.family == "T" and (bool(assignment_evidence) or device.status == "removed")
            or device.family == "C" and (cohort or facts.camera_evidence is not None)
        )
        if cohort and device.family == "T" and facts.ignition_on is not True:
            context_needed = False
        if asset is not None and context_needed:
            candidates, conflicts, removals = self._asset_trackers(asset)
            recent = _recent_trackers(candidates, self.snapshot.at_us, self.recent_us)
            if device.serial in removals:
                assignment_evidence = removals[device.serial]
                asset = None
                documented_removed = True
            elif device.family == "T":
                contenders = [tracker for tracker in recent if tracker.assignment.evidence]
                if len(contenders) > 1 and any(tracker.device.serial == device.serial for tracker in contenders):
                    assignment_ambiguous = True
                    assignment_evidence = tuple(event for tracker in contenders for event in tracker.evidence)
            elif device.family == "C":
                plausible = recent or candidates
                verified = [tracker for tracker in plausible if tracker.assignment.evidence]
                contenders = verified or plausible
                tracker_ambiguous = bool(conflicts) or len(contenders) > 1
                if tracker_ambiguous:
                    tracker_evidence = conflicts + tuple(event for tracker in contenders for event in tracker.evidence)
                elif contenders:
                    selected = contenders[0]
                    tracker_facts = self._project(selected.device.serial, cohort_tracker=cohort)
                    tracker_evidence = selected.assignment.evidence

        if facts is None:
            mode = tracker_facts.ignition_since if tracker_facts and tracker_facts.ignition_on else None
            events = self.snapshot.camera_cohort_facts(device.serial, mode.observed_us) if mode is not None else ()
            facts = project_device(self.snapshot.at_us, events)

        return DeviceContext(
            device=device,
            facts=facts,
            asset_id=asset.asset_id if asset is not None else None,
            assignment_evidence=assignment_evidence,
            tracker_facts=tracker_facts,
            tracker_evidence=tracker_evidence,
            tracker_ambiguous=tracker_ambiguous,
            asset=asset,
            weather=self.references.weather,
            assignment_ambiguous=assignment_ambiguous,
            documented_removed=documented_removed,
        )


def load_device_context(
    store: EventStore, references: References, device: Device, at_us: int, rules: RulesConfig,
) -> DeviceContext:
    """Copy one device's related receipts from one committed history."""
    with store.read_snapshot(at_us) as snapshot:
        return DeviceContextReader(snapshot, references, rules).read(device)
