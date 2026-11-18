"""Validate one event and preserve its receipt, observation and identity."""

import hashlib
import json
from dataclasses import dataclass
from enum import StrEnum
from math import isfinite

from .time_utils import parse_packet_time_us


class TimeQuality(StrEnum):
    CREDIBLE = "credible"
    CLOCK_AHEAD = "clock_ahead"
    UNDECODED = "undecoded"


class InvalidEvent(ValueError):
    """An individual event failed validation."""


@dataclass(frozen=True, slots=True)
class NormalizedEvent:
    event_id: str
    serial: str | None
    raw_type: str
    kind: str
    observed_us: int | None
    received_us: int
    raw_device_time_json: str | None
    payload_json: str
    fingerprint: bytes
    envelope_hash: bytes
    device_origin: bool
    time_quality: TimeQuality


_PLATFORM_TYPES = {"command", "plan_change"}
_DEVICE_TYPES = {
    "position", "heartbeat", "ignition_on", "ignition_off", "power_disconnect",
    "power_restore", "low_voltage", "camera_status", "check_in",
}
_KNOWN_TYPES = _PLATFORM_TYPES | _DEVICE_TYPES | {"bx_raw"}
_COORDINATES = {"lat": (-90, 90), "lng": (-180, 180)}
_NUMBER_BOUNDS = {
    "position": {**_COORDINATES, "speed_kmh": (0, None)},
    "heartbeat": {"battery_v": (None, None), "signal": (0, 5)},
    "low_voltage": {"volts": (None, None)},
    "check_in": {**_COORDINATES, "battery_pct": (0, 100), "temp_c": (None, None)},
}
_TEXT_FIELDS = {
    "heartbeat": ("vin",),
    "ignition_on": ("vin",),
    "low_voltage": ("source",),
    "command": ("command", "issued_by"),
    "plan_change": ("plan", "reason"),
}
_STATUS_VALUES = {
    "camera_status": ("booting", "recording", "sleeping", "storage_error"),
    "plan_change": ("active", "paused", "ended"),
}


def _text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise InvalidEvent(f"{field} must be a nonblank string")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise InvalidEvent(f"{field} contains invalid Unicode") from exc
    return value


def _time_us(value: object, field: str, *, allow_epoch_seconds: bool = False) -> int:
    try:
        return parse_packet_time_us(value, allow_epoch_seconds=allow_epoch_seconds)
    except ValueError as exc:
        raise InvalidEvent(f"invalid {field}: {exc}") from exc


def _canonical_json(value: object) -> str:
    try:
        return json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError, RecursionError) as exc:
        raise InvalidEvent("event contains unsupported JSON data") from exc


def _validate_payload(payload: object, kind: str) -> dict:
    if not isinstance(payload, dict):
        raise InvalidEvent("payload must be an object")

    for field, (lower, upper) in _NUMBER_BOUNDS.get(kind, {}).items():
        value = payload.get(field)
        if type(value) not in (int, float) or (type(value) is float and not isfinite(value)):
            raise InvalidEvent(f"payload.{field} must be a finite number")
        if (lower is not None and value < lower) or (upper is not None and value > upper):
            raise InvalidEvent(f"payload.{field} is out of range")

    for field in _TEXT_FIELDS.get(kind, ()):
        _text(payload.get(field), f"payload.{field}")
    if kind == "position" and type(payload.get("ignition")) is not bool:
        raise InvalidEvent("payload.ignition must be a boolean")
    if kind in _STATUS_VALUES and payload.get("status") not in _STATUS_VALUES[kind]:
        raise InvalidEvent("payload.status is outside the allowed values")
    if kind == "camera_status" and "code" in payload:
        _text(payload["code"], "payload.code")
    return payload


def normalize_event(raw: object, *, clock_ahead_tolerance_seconds: int) -> NormalizedEvent | None:
    """Return a validated observation, or ignore an unused type after checking its envelope."""
    if not isinstance(raw, dict):
        raise InvalidEvent("event must be an object")
    event_id = _text(raw.get("event_id"), "event_id")
    kind = _text(raw.get("type"), "type")
    received_us = _time_us(raw.get("received_at"), "received_at")
    if kind not in _KNOWN_TYPES:
        return None

    if kind == "bx_raw":
        serial = observed_us = raw_device_time_json = None
        payload = {"raw": _text(raw.get("raw"), "raw")}
        time_quality = TimeQuality.UNDECODED
    else:
        serial = _text(raw.get("serial"), "serial")
        device_time = raw.get("device_time")
        observed_us = _time_us(device_time, "device_time", allow_epoch_seconds=kind == "check_in")
        raw_device_time_json = _canonical_json(device_time)
        payload = _validate_payload(raw.get("payload"), kind)
        time_quality = (
            TimeQuality.CLOCK_AHEAD
            if observed_us - received_us > clock_ahead_tolerance_seconds * 1_000_000
            else TimeQuality.CREDIBLE
        )

    # The canonical source payload preserves names, JSON numeric forms and extra
    # fields. An opaque BX frame keeps its exact text until the decoder phase.
    identity = _canonical_json((serial, kind, observed_us, payload))
    return NormalizedEvent(
        event_id=event_id,
        serial=serial,
        raw_type=kind,
        kind=kind,
        observed_us=observed_us,
        received_us=received_us,
        raw_device_time_json=raw_device_time_json,
        payload_json=_canonical_json(payload),
        fingerprint=hashlib.sha256(identity.encode("ascii")).digest(),
        envelope_hash=hashlib.sha256(_canonical_json(raw).encode("ascii")).digest(),
        device_origin=kind in _DEVICE_TYPES,
        time_quality=time_quality,
    )
