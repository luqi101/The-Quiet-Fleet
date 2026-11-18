"""Load the six reference CSVs without reading event history."""

from __future__ import annotations

import csv
import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass, fields
from datetime import date, datetime, timezone
from operator import attrgetter
from pathlib import Path
from types import MappingProxyType


class ReferenceDataError(ValueError):
    """A required reference file could not be loaded."""


@dataclass(frozen=True, slots=True)
class Asset:
    asset_id: str
    type: str
    depot: str
    use: str | None
    make_model: str | None
    year: str | None
    vin: str | None
    status: str


@dataclass(frozen=True, slots=True)
class Device:
    serial: str
    family: str
    model: str | None
    firmware: str | None
    carrier: str | None
    asset_id: str | None
    status: str
    installed_at: date | datetime | None


@dataclass(frozen=True, slots=True)
class Job:
    job_id: str
    asset_id: str
    depot: str
    start: datetime
    end: datetime
    job_type: str


@dataclass(frozen=True, slots=True)
class Weather:
    date: date
    depot: str
    low_c: float
    high_c: float


@dataclass(frozen=True, slots=True)
class PlanChange:
    serial: str
    time: datetime
    plan: str
    status: str
    reason: str | None
    event_id: str


@dataclass(frozen=True, slots=True)
class SupportCase:
    case_id: str
    opened_at: datetime
    closed_at: datetime
    depot: str
    asset_id: str | None
    serial: str | None
    reported_by: str | None
    symptom: str | None
    root_cause: str
    action: str | None
    outcome: str | None
    notes: str | None

    @property
    def duration_is_negative(self) -> bool:
        """Flag an unusable historical duration while retaining both timestamps."""
        return self.closed_at < self.opened_at


@dataclass(frozen=True, slots=True)
class References:
    assets: Mapping[str, Asset]
    devices: Mapping[str, Device]
    jobs: Mapping[str, Job]
    weather: Mapping[tuple[str, date], Weather]
    plan_changes: Mapping[str, PlanChange]
    support_cases: Mapping[str, SupportCase]


type CsvRow = dict[str, str]
type ReferenceRow = Asset | Device | Job | Weather | PlanChange | SupportCase

DEPOTS = ("MSS", "REG")


def _load_table[Key, Row: ReferenceRow](
    path: Path,
    row_type: type[Row],
    parse: Callable[[CsvRow], Row],
    primary_key: Callable[[Row], Key],
) -> Mapping[Key, Row]:
    rows: dict[Key, Row] = {}
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream, strict=True)
            headers = reader.fieldnames or []
            expected = {field.name for field in fields(row_type)}
            if len(headers) != len(set(headers)):
                raise ReferenceDataError(f"{path}:1: duplicate CSV column")
            if set(headers) != expected:
                missing = ", ".join(sorted(expected - set(headers))) or "none"
                extra = ", ".join(sorted(set(headers) - expected)) or "none"
                raise ReferenceDataError(f"{path}:1: incorrect columns (missing {missing}, extra {extra})")
            for raw in reader:
                line = reader.line_num
                if None in raw or any(value is None for value in raw.values()):
                    raise ReferenceDataError(f"{path}:{line}: row does not match the CSV columns")
                try:
                    record = parse(raw)
                except ValueError as error:
                    raise ReferenceDataError(f"{path}:{line}: {error}") from error
                key = primary_key(record)
                if key in rows:
                    raise ReferenceDataError(f"{path}:{line}: duplicate primary key {key!r}")
                rows[key] = record
    except (csv.Error, UnicodeError) as error:
        raise ReferenceDataError(f"{path}:{max(1, reader.reader.line_num)}: invalid CSV ({error})") from error
    except OSError as error:
        raise ReferenceDataError(f"{path}: {error.strerror or error}") from error
    return MappingProxyType(rows)


def _optional(row: CsvRow, field: str) -> str | None:
    text = row[field]
    return text if text.strip() else None


def _required(row: CsvRow, field: str) -> str:
    text = _optional(row, field)
    if text is None:
        raise ValueError(f"{field} is required")
    return text


def _choice(row: CsvRow, field: str, allowed: tuple[str, ...]) -> str:
    value = _required(row, field)
    if value not in allowed:
        raise ValueError(f"invalid {field} {value!r}")
    return value


def _utc(row: CsvRow, field: str) -> datetime:
    text = _required(row, field)
    try:
        value = datetime.fromisoformat(text)
        if value.utcoffset() is not None:
            return value.astimezone(timezone.utc)
    except (ValueError, OverflowError):
        pass
    raise ValueError(f"{field} must be a timezone-aware ISO timestamp")


def _local_date(row: CsvRow, field: str) -> date:
    text = _required(row, field)
    try:
        return date.fromisoformat(text)
    except ValueError as error:
        raise ValueError(f"{field} must be an ISO date") from error


def _number(row: CsvRow, field: str) -> float:
    text = _required(row, field)
    try:
        value = float(text)
    except ValueError as error:
        raise ValueError(f"{field} must be a finite number") from error
    if not math.isfinite(value):
        raise ValueError(f"{field} must be a finite number")
    return value


def _known_identity(
    value: str | None, catalog: Mapping[str, ReferenceRow], field: str
) -> None:
    if value is not None and value not in catalog:
        raise ValueError(f"{field} {value!r} is absent from its reference table")


def _asset(row: CsvRow) -> Asset:
    return Asset(
        asset_id=_required(row, "asset_id"),
        type=_choice(row, "type", ("van", "pickup", "trailer", "equipment")),
        depot=_choice(row, "depot", DEPOTS),
        use=_optional(row, "use"),
        make_model=_optional(row, "make_model"),
        year=_optional(row, "year"),
        vin=_optional(row, "vin"),
        status=_required(row, "status"),
    )


def _device(row: CsvRow, assets: Mapping[str, Asset]) -> Device:
    asset_id = _optional(row, "asset_id")
    _known_identity(asset_id, assets, "asset_id")
    installed = _optional(row, "installed_at")
    installed_at = None
    if installed is not None:
        try:
            installed_at = date.fromisoformat(installed)
        except ValueError:
            installed_at = _utc(row, "installed_at")
    return Device(
        serial=_required(row, "serial"),
        family=_choice(row, "family", ("T", "C", "A", "BX")),
        model=_optional(row, "model"),
        firmware=_optional(row, "firmware"),
        carrier=_optional(row, "carrier"),
        asset_id=asset_id,
        status=_choice(row, "status", ("active", "stock", "removed")),
        installed_at=installed_at,
    )


def _job(row: CsvRow, assets: Mapping[str, Asset]) -> Job:
    asset_id = _required(row, "asset_id")
    _known_identity(asset_id, assets, "asset_id")
    start, end = _utc(row, "start"), _utc(row, "end")
    if end <= start:
        raise ValueError("job end must be later than start")
    return Job(
        job_id=_required(row, "job_id"),
        asset_id=asset_id,
        depot=_choice(row, "depot", DEPOTS),
        start=start,
        end=end,
        job_type=_required(row, "job_type"),
    )


def _weather(row: CsvRow) -> Weather:
    low, high = _number(row, "low_c"), _number(row, "high_c")
    if high < low:
        raise ValueError("high_c must be at least low_c")
    return Weather(
        date=_local_date(row, "date"),
        depot=_choice(row, "depot", DEPOTS),
        low_c=low,
        high_c=high,
    )


def _plan_change(row: CsvRow, devices: Mapping[str, Device]) -> PlanChange:
    serial = _required(row, "serial")
    _known_identity(serial, devices, "serial")
    return PlanChange(
        serial=serial,
        time=_utc(row, "time"),
        plan=_required(row, "plan"),
        status=_choice(row, "status", ("active", "paused", "ended")),
        reason=_optional(row, "reason"),
        event_id=_required(row, "event_id"),
    )


def _support_case(
    row: CsvRow, assets: Mapping[str, Asset], devices: Mapping[str, Device]
) -> SupportCase:
    asset_id = _optional(row, "asset_id")
    serial = _optional(row, "serial")
    _known_identity(asset_id, assets, "asset_id")
    _known_identity(serial, devices, "serial")
    return SupportCase(
        case_id=_required(row, "case_id"),
        opened_at=_utc(row, "opened_at"),
        closed_at=_utc(row, "closed_at"),
        depot=_choice(row, "depot", DEPOTS),
        asset_id=asset_id,
        serial=serial,
        reported_by=_optional(row, "reported_by"),
        symptom=_optional(row, "symptom"),
        root_cause=_required(row, "root_cause"),
        action=_optional(row, "action"),
        outcome=_optional(row, "outcome"),
        notes=_optional(row, "notes"),
    )


def load_references(data_dir: Path) -> References:
    assets = _load_table(data_dir / "assets.csv", Asset, _asset, attrgetter("asset_id"))
    devices = _load_table(
        data_dir / "devices.csv", Device, lambda row: _device(row, assets), attrgetter("serial")
    )
    return References(
        assets=assets,
        devices=devices,
        jobs=_load_table(
            data_dir / "schedule.csv", Job, lambda row: _job(row, assets), attrgetter("job_id")
        ),
        weather=_load_table(
            data_dir / "weather.csv", Weather, _weather, attrgetter("depot", "date")
        ),
        plan_changes=_load_table(
            data_dir / "plan_changes.csv",
            PlanChange,
            lambda row: _plan_change(row, devices),
            attrgetter("event_id"),
        ),
        support_cases=_load_table(
            data_dir / "support_cases.csv",
            SupportCase,
            lambda row: _support_case(row, assets, devices),
            attrgetter("case_id"),
        ),
    )
