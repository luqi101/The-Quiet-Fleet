"""Decode the inferred BX wire format without consulting sample files."""

import json
import re
from dataclasses import dataclass
from math import isfinite
from typing import NoReturn

from .config import WireFormatConstants
from .time_utils import parse_packet_time_us


BX_REPORT = "bx_report"
_BX_FIELDS = {"u", "t", "b", "s", "p"}
_HEX_CLOCK = re.compile(r"[0-9a-fA-F]+")
_COORDINATE_PAIR = re.compile(r"[ \t]*([+-]?[0-9]+)[ \t]*,[ \t]*([+-]?[0-9]+)[ \t]*")


class InvalidBX(ValueError):
    """The BX reading could not be decoded."""


@dataclass(frozen=True, slots=True)
class BXFrame:
    serial: str
    observed_us: int
    clock_hex: str
    payload: dict[str, object]


def _reject_constant(token: str) -> NoReturn:
    raise InvalidBX(f"{token} is outside the BX JSON grammar")


def _finite_float(text: str) -> float:
    number = float(text)
    if not isfinite(number):
        raise InvalidBX("BX JSON numbers must be finite")
    return number


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result = dict(pairs)
    if len(result) != len(pairs):
        raise InvalidBX("BX JSON keys must be unique")
    return result


def decode_bx(raw: object, rules: WireFormatConstants) -> BXFrame:
    if not isinstance(raw, str):
        raise InvalidBX("BX raw must be a JSON string")
    try:
        frame = json.loads(raw, parse_constant=_reject_constant, parse_float=_finite_float, object_pairs_hook=_unique_object)
    except (ValueError, RecursionError) as exc:
        raise InvalidBX("invalid BX JSON") from exc
    if not isinstance(frame, dict):
        raise InvalidBX("BX raw must contain a JSON object")

    serial, clock, battery, flags, point = (frame.get(key) for key in ("u", "t", "b", "s", "p"))
    if not isinstance(serial, str) or not serial.strip():
        raise InvalidBX("BX u must be a nonblank serial")
    if not isinstance(clock, str) or _HEX_CLOCK.fullmatch(clock) is None:
        raise InvalidBX("BX t must be hexadecimal Unix seconds")
    try:
        observed_us = parse_packet_time_us(int(clock, rules.bx_epoch_radix.value), rules, allow_epoch_seconds=True)
    except ValueError as exc:
        raise InvalidBX("BX t is outside the supported epoch-second range") from exc

    full_scale = rules.bx_battery_full_scale.value
    if type(battery) is not int or not 0 <= battery <= full_scale:
        raise InvalidBX("BX b must be an integer within the raw battery range")
    if type(flags) is not int or flags < 0:
        raise InvalidBX("BX s must be a nonnegative integer bit field")
    coordinates = _COORDINATE_PAIR.fullmatch(point) if isinstance(point, str) else None
    if coordinates is None:
        raise InvalidBX("BX p must contain exactly two signed decimal integers")
    try:
        lat_code, lng_code = map(int, coordinates.groups())
    except ValueError as exc:
        raise InvalidBX("BX coordinate integers are out of range") from exc
    scale = rules.bx_coordinate_scale.value
    if not (-90 * scale <= lat_code <= 90 * scale and -180 * scale <= lng_code <= 180 * scale):
        raise InvalidBX("BX coordinates are outside geographic bounds")

    moving, low, fix = rules.bx_moving_mask.value, rules.bx_battery_low_mask.value, rules.bx_gps_fix_mask.value
    has_fix = bool(flags & fix)
    return BXFrame(serial, observed_us, clock, {
        "battery_raw": battery,
        "battery_pct": 100 * battery / full_scale,
        "flags": flags,
        "moving": bool(flags & moving),
        "low_battery": bool(flags & low),
        "gps_fix": has_fix,
        "unknown_flags": flags & ~(moving | low | fix),
        "coordinate_codes": [lat_code, lng_code],
        "lat": lat_code / scale if has_fix else None,
        "lng": lng_code / scale if has_fix else None,
        "extra": {key: value for key, value in frame.items() if key not in _BX_FIELDS},
    })
