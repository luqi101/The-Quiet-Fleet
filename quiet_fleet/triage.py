"""Share carrier decisions between device status and the support queue."""

from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
import json

from .asset_context import DeviceContextReader
from .config import RulesConfig
from .diagnosis import assess_device
from .incidents import Incident, detect_incidents
from .models import DeviceState, DeviceStatus, ItemKind, Priority, TriageItem, TriageResponse
from .reference import Device, References
from .reporting_peers import reporting_peer
from .store import EventStore, ReadSnapshot
from .time_utils import to_epoch_us


_PRIORITY_ORDER = {Priority.HIGH: 0, Priority.MEDIUM: 1, Priority.LOW: 2}


@dataclass(frozen=True, slots=True)
class _IncidentView:
    revision: int
    at_us: int
    incidents: tuple[Incident, ...]
    by_serial: dict[str, Incident]


class SupportView:
    def __init__(self, rules: RulesConfig, references: References, store: EventStore) -> None:
        self.rules = rules
        self.references = references
        self.store = store
        self._last: _IncidentView | None = None

    def _incidents(self, snapshot: ReadSnapshot) -> _IncidentView:
        # This single-entry memo is accessed only under the store snapshot
        # lock. The committed revision includes earlier-receipt aliases.
        last = self._last
        if last is None or (last.revision, last.at_us) != (snapshot.revision, snapshot.at_us):
            incidents = detect_incidents(snapshot, self.references, self.rules)
            by_serial = {serial: incident for incident in incidents for serial in incident.item.serials}
            assert len(by_serial) == sum(len(incident.item.serials) for incident in incidents)
            last = _IncidentView(snapshot.revision, snapshot.at_us, incidents, by_serial)
            self._last = last
        return last

    def status(self, at: datetime, device: Device) -> DeviceStatus:
        at_us = to_epoch_us(at)
        with self.store.read_snapshot(at_us) as snapshot:
            context = DeviceContextReader(snapshot, self.references, self.rules).read(device)
            status = assess_device(at, self.rules, context).status
            peer = reporting_peer(context, at_us, self.rules)
            if peer is None or peer.missing_since_us is None:
                return status
            incident = self._incidents(snapshot).by_serial.get(device.serial)
        if incident is None:
            return status
        item = incident.item
        return status.model_copy(update={
            "state": DeviceState.NEEDS_ACTION,
            "likely_cause": item.likely_cause,
            "confidence": incident.confidence,
            "reasons": [*item.reasons, item.next_action],
            "evidence": list(dict.fromkeys((*item.evidence, *status.evidence))),
        })

    def triage(self, at: datetime) -> TriageResponse:
        with self.store.read_snapshot(to_epoch_us(at)) as snapshot:
            grouped = self._incidents(snapshot)
            items = [incident.item for incident in grouped.incidents]
            reader = DeviceContextReader(snapshot, self.references, self.rules)
            for device in self.references.devices.values():
                if device.serial in grouped.by_serial:
                    continue
                assessment = assess_device(at, self.rules, reader.read(device))
                if assessment.next_action is None or assessment.priority is None:
                    continue
                status = assessment.status
                identifier = sha256(json.dumps((status.serial, status.likely_cause)).encode("ascii")).hexdigest()
                items.append(TriageItem(
                    item_id=f"device-{identifier[:24]}",
                    kind=ItemKind.DEVICE,
                    serials=[status.serial],
                    asset_ids=[status.asset_id] if status.asset_id is not None else [],
                    likely_cause=status.likely_cause,
                    who_acts=assessment.owner,
                    next_action=assessment.next_action,
                    priority=assessment.priority,
                    reasons=status.reasons,
                    evidence=status.evidence,
                ))
        items.sort(key=lambda item: (_PRIORITY_ORDER[item.priority], item.item_id))
        return TriageResponse(at=at, items=items)
