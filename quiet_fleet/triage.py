"""Evaluate support status and queue items from one committed as-of context."""

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from types import MappingProxyType

from .asset_context import DeviceContext, DeviceContextReader
from .config import RulesConfig
from .diagnosis import assess_device
from .fault import owned_action
from .incidents import Incident, detect_incidents
from .models import DeviceState, DeviceStatus, ItemKind, Priority, TriageItem, TriageResponse, WhoActs
from .operations import OperationalContext, Operations, Work
from .reference import Device, References
from .reporting_peers import reporting_peer
from .store import EventStore, ReadSnapshot
from .time_utils import from_epoch_us, to_epoch_us


_PRIORITY_ORDER = {Priority.HIGH: 0, Priority.MEDIUM: 1, Priority.LOW: 2}


@dataclass(frozen=True, slots=True)
class _IncidentView:
    revision: int
    at_us: int
    incidents: tuple[Incident, ...]
    by_serial: Mapping[str, Incident]


@dataclass(frozen=True, slots=True)
class _QueueEntry:
    item: TriageItem
    deadline: datetime | None

    def order(self) -> tuple:
        item = self.item
        return (
            _PRIORITY_ORDER[item.priority], self.deadline is None, self.deadline,
            item.likely_cause, item.asset_ids, item.serials, item.item_id,
        )


def _reasons(observations: tuple[str, ...] | list[str], work: Work) -> list[str]:
    operational = work.reason()
    return list(dict.fromkeys((*observations, operational))) if operational else list(dict.fromkeys(observations))


@dataclass(frozen=True, slots=True)
class _Evaluation:
    rules: RulesConfig
    operations: OperationalContext
    reader: DeviceContextReader

    def group(self, incident: Incident) -> _QueueEntry:
        work = self.operations.work_for(incident.asset_ids)
        item = TriageItem(
            item_id=incident.item_id,
            kind=ItemKind.INCIDENT,
            serials=list(incident.serials),
            asset_ids=list(incident.asset_ids),
            likely_cause=incident.cause,
            who_acts=incident.owner,
            next_action=incident.next_action,
            priority=self.operations.priority(incident.cause, work, incident_devices=len(incident.serials)),
            reasons=_reasons(incident.reasons, work),
            evidence=list(incident.evidence),
        )
        return _QueueEntry(item, work.deadline)

    def individual(self, context: DeviceContext) -> tuple[DeviceStatus, _QueueEntry | None]:
        assets = [context.asset_id] if context.asset_id is not None else []
        work = self.operations.work_for(assets)
        decision = assess_device(self.operations.at, self.rules, context, operational_risk=work.urgent)
        status, fault = decision.status, decision.fault
        if fault is None or fault.owner == WhoActs.NONE:
            return status, None

        reasons = _reasons(status.reasons, work)
        action = owned_action(fault.owner, fault.next_action)
        tracker = context.tracker_facts
        parked = not context.tracker_ambiguous and tracker is not None and tracker.ignition_on is False
        recheck = from_epoch_us(fault.recheck_us) if fault.recheck_us is not None else None
        identifier = sha256(json.dumps(
            (status.serial, fault.cause, fault.opened_us, context.asset_id if fault.opened_us is None else None),
            ensure_ascii=True, separators=(",", ":"),
        ).encode("ascii")).hexdigest()
        item = TriageItem(
            item_id=f"device-{identifier[:24]}",
            kind=ItemKind.DEVICE,
            serials=[status.serial],
            asset_ids=assets,
            likely_cause=status.likely_cause,
            who_acts=fault.owner,
            next_action=action,
            priority=self.operations.priority(fault.cause, work, parked_camera=parked, recheck_at=recheck),
            reasons=reasons,
            evidence=status.evidence,
        )
        return status.model_copy(update={"reasons": [*reasons, action]}), _QueueEntry(item, work.deadline)


class SupportView:
    def __init__(self, rules: RulesConfig, references: References, store: EventStore) -> None:
        self.rules = rules
        self.references = references
        self.store = store
        self.operations = Operations(references.jobs.values(), rules)
        self._queue_devices = tuple(sorted(
            references.devices.values(), key=lambda device: (device.asset_id or "", device.family != "T", device.serial),
        ))
        self._last: _IncidentView | None = None

    def _evaluation(self, at: datetime, snapshot: ReadSnapshot) -> _Evaluation:
        return _Evaluation(self.rules, self.operations.at(at), DeviceContextReader(snapshot, self.references, self.rules))

    def _incidents(self, snapshot: ReadSnapshot) -> _IncidentView:
        # The store snapshot lock protects this single-entry memo, including
        # invalidation when an earlier original receipt changes the evidence.
        last = self._last
        if last is None or (last.revision, last.at_us) != (snapshot.revision, snapshot.at_us):
            incidents = detect_incidents(snapshot, self.references, self.rules)
            by_serial = {serial: incident for incident in incidents for serial in incident.serials}
            assert len(by_serial) == sum(len(incident.serials) for incident in incidents)
            last = _IncidentView(snapshot.revision, snapshot.at_us, incidents, MappingProxyType(by_serial))
            self._last = last
        return last

    def status(self, at: datetime, device: Device) -> DeviceStatus:
        at_us = to_epoch_us(at)
        with self.store.read_snapshot(at_us) as snapshot:
            evaluation = self._evaluation(at, snapshot)
            context = evaluation.reader.read(device)
            peer = reporting_peer(context, at_us, self.rules)
            if peer is not None and peer.missing_since_us is not None:
                incident = self._incidents(snapshot).by_serial.get(device.serial)
                if incident is not None:
                    item = evaluation.group(incident).item
                    contact = context.facts.last_contact
                    assert contact is not None
                    return DeviceStatus(
                        serial=device.serial,
                        asset_id=context.asset_id,
                        at=at,
                        state=DeviceState.NEEDS_ACTION,
                        likely_cause=incident.cause,
                        confidence=incident.confidence,
                        last_heard_at=from_epoch_us(contact.first_received_us),
                        reasons=[*item.reasons, item.next_action],
                        evidence=list(dict.fromkeys((*item.evidence, contact.event_id))),
                    )
            return evaluation.individual(context)[0]

    def triage(self, at: datetime) -> TriageResponse:
        with self.store.read_snapshot(to_epoch_us(at)) as snapshot:
            grouped = self._incidents(snapshot)
            evaluation = self._evaluation(at, snapshot)
            entries = [evaluation.group(incident) for incident in grouped.incidents]
            for device in self._queue_devices:
                if device.serial in grouped.by_serial:
                    continue
                _, entry = evaluation.individual(evaluation.reader.read(device))
                if entry is not None:
                    entries.append(entry)
        return TriageResponse(at=at, items=[entry.item for entry in sorted(entries, key=_QueueEntry.order)])
