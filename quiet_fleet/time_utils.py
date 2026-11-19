"""Parse explicit UTC instants and represent them as exact epoch microseconds."""

import re
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import MappingProxyType
from zoneinfo import ZoneInfo

from .config import WireFormatConstants


_ISO_INSTANT = re.compile(
    r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}"
    r"(?:\.[0-9]{1,6})?(?:Z|[+-](?:[01][0-9]|2[0-3]):[0-5][0-9])"
)
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_MICROSECONDS = 1_000_000


DEPOT_ZONES = MappingProxyType({
    "MSS": ZoneInfo("America/Toronto"),
    "REG": ZoneInfo("America/Regina"),
})


def utc_text(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().removesuffix("+00:00") + "Z"


def parse_iso_instant(value: object) -> datetime:
    """Require a date, time to seconds, and an explicit offset. Return UTC."""
    if not isinstance(value, str) or _ISO_INSTANT.fullmatch(value) is None:
        raise ValueError("expected an ISO timestamp with an explicit offset")
    try:
        return datetime.fromisoformat(value).astimezone(UTC)
    except (ValueError, OverflowError) as exc:
        raise ValueError("invalid ISO timestamp") from exc


def to_epoch_us(value: datetime) -> int:
    if value.utcoffset() is None:
        raise ValueError("expected a timezone-aware timestamp")
    delta = value.astimezone(UTC) - _EPOCH
    return (delta.days * 86_400 + delta.seconds) * _MICROSECONDS + delta.microseconds


def from_epoch_us(value: int) -> datetime:
    if type(value) is not int:
        raise ValueError("expected integer epoch microseconds")
    return _EPOCH + timedelta(microseconds=value)


def parse_packet_time_us(value: object, rules: WireFormatConstants, *, allow_epoch_seconds: bool = False) -> int:
    """Accept packet instants within the configured UTC range at microsecond precision.

    Numeric Unix seconds are opt-in. A numeric value must represent an
    exact number of microseconds. The parser never guesses milliseconds.
    """
    lower = rules.packet_epoch_start_seconds.value
    upper = rules.packet_epoch_end_seconds_exclusive.value
    if allow_epoch_seconds and type(value) in (int, float):
        if not lower <= value < upper:
            raise ValueError("numeric packet time is outside the supported epoch-second range")
        numerator, denominator = Decimal(str(value)).as_integer_ratio()
        microseconds, remainder = divmod(numerator * _MICROSECONDS, denominator)
        if remainder:
            raise ValueError("numeric packet time exceeds microsecond precision")
        return microseconds

    microseconds = to_epoch_us(parse_iso_instant(value))
    if not lower * _MICROSECONDS <= microseconds < upper * _MICROSECONDS:
        raise ValueError("packet time is outside the supported UTC range")
    return microseconds
