"""Project device facts from an immutable as-of event snapshot."""

import json
from dataclasses import dataclass

from .store import EventFact


@dataclass(frozen=True, slots=True)
class DeviceFacts:
    last_contact: EventFact | None
    freshest_measurement: EventFact | None
    observations: tuple[EventFact, ...]
    ignition_on: bool | None
    ignition_evidence: EventFact | None
    ignition_since: EventFact | None
    camera_status: str | None
    camera_evidence: EventFact | None
    camera_storage_error: EventFact | None
    power_disconnect: EventFact | None
    reboot_commands: tuple[EventFact, ...]
    plan_status: str | None
    plan_evidence: EventFact | None
    battery_pct: float | None
    battery_evidence: EventFact | None


def _receipt_key(event: EventFact) -> tuple[int, str]:
    return event.first_received_us, event.event_id


def _observed_time(event: EventFact) -> int:
    assert event.observed_us is not None
    return event.observed_us


def _observation_key(event: EventFact) -> tuple[int, int, str]:
    return _observed_time(event), event.first_received_us, event.event_id


def project_device(at_us: int, events: tuple[EventFact, ...]) -> DeviceFacts:
    """Use eligible receipts for contact and eligible observations for device facts.

    Each event represents one logical message. The store resolves original receipt
    aliases before supplying the snapshot.
    """
    available = tuple(event for event in events if event.first_received_us <= at_us)
    last_contact = max((event for event in available if event.device_origin), key=_receipt_key, default=None)
    observations = tuple(sorted(
        (
            event for event in available
            if event.time_quality == "credible" and event.observed_us is not None and event.observed_us <= at_us
        ),
        key=_observation_key,
    ))
    freshest_measurement = next((event for event in reversed(observations) if event.device_origin), None)

    ignition_on = ignition_evidence = ignition_since = None
    camera_status = camera_evidence = camera_storage_error = None
    power_disconnect = None
    reboot_commands = []
    plan_status = plan_evidence = None
    battery_pct = battery_evidence = None

    for event in observations:
        kind = event.kind
        if kind in {"ignition_on", "ignition_off"}:
            ignition_on, ignition_evidence = kind == "ignition_on", event
            ignition_since = event
        elif kind == "position":
            ignition = json.loads(event.payload_json).get("ignition")
            explicit_at_same_instant = (
                ignition_evidence is not None
                and ignition_evidence.kind in {"ignition_on", "ignition_off"}
                and ignition_evidence.observed_us == event.observed_us
            )
            if isinstance(ignition, bool) and not explicit_at_same_instant:
                if ignition_on is not ignition:
                    ignition_since = event
                ignition_on, ignition_evidence = ignition, event
        elif kind == "camera_status":
            status = json.loads(event.payload_json).get("status")
            if status in {"booting", "recording", "sleeping", "storage_error"}:
                camera_status, camera_evidence = status, event
            if status == "storage_error":
                camera_storage_error = event
            elif status == "recording" and camera_storage_error is not None:
                if _observed_time(event) > _observed_time(camera_storage_error):
                    camera_storage_error = None
        elif kind == "power_disconnect":
            power_disconnect = event
        elif kind == "power_restore" and power_disconnect is not None:
            if _observed_time(event) > _observed_time(power_disconnect):
                power_disconnect = None
        elif kind == "command" and json.loads(event.payload_json).get("command") == "reboot":
            reboot_commands.append(event)
        elif kind == "plan_change":
            status = json.loads(event.payload_json).get("status")
            if status in {"active", "paused", "ended"}:
                plan_status, plan_evidence = status, event
        elif kind == "check_in":
            value = json.loads(event.payload_json).get("battery_pct")
            if type(value) in (float, int) and 0 <= value <= 100:
                battery_pct, battery_evidence = float(value), event

    return DeviceFacts(
        last_contact=last_contact,
        freshest_measurement=freshest_measurement,
        observations=observations,
        ignition_on=ignition_on,
        ignition_evidence=ignition_evidence,
        ignition_since=ignition_since,
        camera_status=camera_status,
        camera_evidence=camera_evidence,
        camera_storage_error=camera_storage_error,
        power_disconnect=power_disconnect,
        reboot_commands=tuple(reboot_commands),
        plan_status=plan_status,
        plan_evidence=plan_evidence,
        battery_pct=battery_pct,
        battery_evidence=battery_evidence,
    )
