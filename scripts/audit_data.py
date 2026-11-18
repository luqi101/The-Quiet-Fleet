"""Reconstruct and audit the supplied history locally for development."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
import sqlite3
import tempfile
from collections import Counter, defaultdict
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
REFERENCE_KEYS = {
    "assets": ("asset_id",),
    "devices": ("serial",),
    "schedule": ("job_id",),
    "weather": ("depot", "date"),
    "plan_changes": ("event_id",),
    "support_cases": ("case_id",),
}
EVENT_FIELDS = {
    "position": ("lat", "lng", "speed_kmh", "ignition"),
    "heartbeat": ("battery_v", "signal", "vin"),
    "ignition_on": ("vin",),
    "ignition_off": (),
    "power_disconnect": (),
    "power_restore": (),
    "low_voltage": ("volts", "source"),
    "camera_status": ("status",),
    "command": ("command", "issued_by"),
    "plan_change": ("plan", "status", "reason"),
    "check_in": ("battery_pct", "lat", "lng", "temp_c"),
}
NUMERIC_FIELDS = {
    "position": ("lat", "lng", "speed_kmh"),
    "heartbeat": ("battery_v", "signal"),
    "low_voltage": ("volts",),
    "check_in": ("battery_pct", "lat", "lng", "temp_c"),
}
TEXT_FIELDS = {
    "heartbeat": ("vin",),
    "ignition_on": ("vin",),
    "low_voltage": ("source",),
    "camera_status": ("status",),
    "command": ("command", "issued_by"),
    "plan_change": ("plan", "status", "reason"),
}
ZONES = {"MSS": "America/Toronto", "REG": "America/Regina"}
CREATE_SCHEMA = """
CREATE TABLE events (
    serial TEXT NOT NULL,
    kind TEXT NOT NULL,
    observed REAL NOT NULL,
    received REAL NOT NULL,
    event_id TEXT NOT NULL,
    payload TEXT NOT NULL,
    UNIQUE(serial, kind, observed, payload)
);
CREATE TABLE event_ids (
    event_id TEXT PRIMARY KEY,
    fingerprint BLOB NOT NULL
) WITHOUT ROWID;
CREATE TABLE retry_receipts (
    observation_rowid INTEGER NOT NULL,
    received REAL NOT NULL
);
"""
OBSERVATION_INSERT = """
INSERT INTO events(serial, kind, observed, received, event_id, payload)
VALUES (?, ?, ?, ?, ?, ?)
ON CONFLICT(serial, kind, observed, payload) DO NOTHING
"""


@dataclass(frozen=True)
class Observation:
    serial: str
    kind: str
    observed: float
    received: float
    event_id: str
    payload: str
    time_format: str

    @property
    def identity(self) -> tuple[str, str, float, str]:
        return self.serial, self.kind, self.observed, self.payload


def canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def parse_time(value: object, allow_epoch: bool = False) -> tuple[float, str]:
    if isinstance(value, str):
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            raise ValueError("timestamp has no UTC offset")
        return parsed.timestamp(), "utc_z" if value.endswith("Z") else "iso_offset"
    if allow_epoch and type(value) in (int, float) and math.isfinite(value):
        return datetime.fromtimestamp(value, timezone.utc).timestamp(), "epoch_seconds"
    raise ValueError("unsupported timestamp")


def utc_text(seconds: float) -> str:
    return datetime.fromtimestamp(seconds, timezone.utc).isoformat().replace("+00:00", "Z")


def required_text(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("empty or nontext identifier")
    return value


def decode_bx(raw: str) -> tuple[str, float, dict]:
    if not isinstance(raw, str):
        raise ValueError("BX raw frame must be a JSON string")
    frame = json.loads(raw)
    if not isinstance(frame, dict):
        raise ValueError("BX raw frame must be an object")

    serial = required_text(frame.get("u"))
    clock = frame.get("t")
    battery = frame.get("b")
    flags = frame.get("s")
    coordinates = required_text(frame.get("p")).split(",")
    if not isinstance(clock, str) or not re.fullmatch(r"[0-9a-fA-F]+", clock):
        raise ValueError("invalid BX hex clock")
    if type(battery) is not int or not 0 <= battery <= 4095:
        raise ValueError("invalid BX battery code")
    if type(flags) is not int or flags < 0:
        raise ValueError("invalid BX flags")
    if len(coordinates) != 2:
        raise ValueError("invalid BX coordinate pair")
    lat, lng = (int(coordinate) / 100_000 for coordinate in coordinates)
    if not -90 <= lat <= 90 or not -180 <= lng <= 180:
        raise ValueError("BX coordinates out of range")

    observed, _ = parse_time(int(clock, 16), allow_epoch=True)
    return serial, observed, {
        "battery_pct": 100 * battery / 4095,
        "battery_raw": battery,
        "moving": bool(flags & 0x01),
        "low_battery": bool(flags & 0x02),
        "gps_fix": bool(flags & 0x08),
        "unknown_flags": flags & ~0x0B,
        "lat": lat,
        "lng": lng,
    }


def _normalize_event(event: dict, devices: dict[str, dict]) -> Observation:
    kind = required_text(event.get("type"))
    event_id = required_text(event.get("event_id"))
    received, _ = parse_time(event.get("received_at"))
    if kind == "bx_raw":
        serial, observed, payload = decode_bx(event.get("raw"))
        time_format = "bx_hex_epoch_seconds"
    else:
        serial = required_text(event.get("serial"))
        is_legacy_tag = devices.get(serial, {}).get("family") == "A"
        observed, time_format = parse_time(event.get("device_time"), allow_epoch=is_legacy_tag)
        payload = event.get("payload")
        if not isinstance(payload, dict) or any(key not in payload for key in EVENT_FIELDS[kind]):
            raise ValueError("invalid event payload shape")
        if any(type(payload[key]) not in (int, float) for key in NUMERIC_FIELDS.get(kind, ())):
            raise ValueError("invalid numeric payload field")
        if any(not isinstance(payload[key], str) for key in TEXT_FIELDS.get(kind, ())):
            raise ValueError("invalid text payload field")
        if kind == "position" and type(payload["ignition"]) is not bool:
            raise ValueError("invalid ignition flag")
        if kind == "camera_status" and payload["status"] not in ("booting", "recording", "sleeping", "storage_error"):
            raise ValueError("invalid camera status")
        if kind == "plan_change" and payload["status"] not in ("active", "paused", "ended"):
            raise ValueError("invalid plan status")
    return Observation(serial, kind, observed, received, event_id, canonical_json(payload), time_format)


def _hash_file(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _load_references(data: Path) -> tuple[dict, dict, dict]:
    refs = {}
    summaries = {}
    source_hashes = {}
    for stem, key_fields in REFERENCE_KEYS.items():
        path = data / f"{stem}.csv"
        source_hashes[path.name] = _hash_file(path)
        with path.open(newline="", encoding="utf-8") as stream:
            reader = csv.DictReader(stream)
            headers = reader.fieldnames or []
            if not set(key_fields).issubset(headers):
                raise ValueError(f"missing primary key columns in {path.name}")
            rows = list(reader)
        keys = {tuple(row[field] for field in key_fields) for row in rows}
        refs[stem] = rows
        summaries[stem] = {
            "rows": len(rows),
            "fields": headers,
            "blank_by_field": {name: sum(not row[name] for row in rows) for name in headers},
            "duplicate_primary_key_excess": len(rows) - len(keys),
            "rows_with_blank_primary_key": sum(any(not row[key] for key in key_fields) for row in rows),
        }

    asset_ids = {row["asset_id"] for row in refs["assets"]}
    serials = {row["serial"] for row in refs["devices"]}
    for stem, field, targets in (
        ("devices", "asset_id", asset_ids),
        ("schedule", "asset_id", asset_ids),
        ("plan_changes", "serial", serials),
        ("support_cases", "asset_id", asset_ids),
        ("support_cases", "serial", serials),
    ):
        missing = sorted({row[field] for row in refs[stem] if row[field] and row[field] not in targets})
        summaries[stem][f"unresolved_{field}"] = missing

    summaries["assets"]["by_status"] = dict(Counter(row["status"] for row in refs["assets"]))
    summaries["assets"]["by_depot_type"] = dict(
        Counter(f"{row['depot']}/{row['type']}" for row in refs["assets"])
    )
    summaries["devices"]["by_family"] = dict(Counter(row["family"] for row in refs["devices"]))
    summaries["devices"]["by_status"] = dict(Counter(row["status"] for row in refs["devices"]))
    summaries["schedule"]["first_start"] = min((row["start"] for row in refs["schedule"]), default=None)
    summaries["schedule"]["last_end"] = max((row["end"] for row in refs["schedule"]), default=None)
    summaries["weather"]["first_date"] = min((row["date"] for row in refs["weather"]), default=None)
    summaries["weather"]["last_date"] = max((row["date"] for row in refs["weather"]), default=None)
    return refs, summaries, source_hashes


def _store_event(conn: sqlite3.Connection, observation: Observation, duplicates: Counter) -> None:
    fingerprint = hashlib.sha256(canonical_json(observation.identity).encode()).digest()
    inserted = conn.execute(
        "INSERT OR IGNORE INTO event_ids(event_id, fingerprint) VALUES (?, ?)",
        (observation.event_id, fingerprint),
    ).rowcount
    if not inserted:
        duplicates["repeated_event_id_excess"] += 1
        existing = conn.execute(
            "SELECT fingerprint FROM event_ids WHERE event_id = ?", (observation.event_id,)
        ).fetchone()
        if existing["fingerprint"] != fingerprint:
            duplicates["conflicting_event_id_envelopes"] += 1
            return

    new_observation = conn.execute(
        OBSERVATION_INSERT,
        (
            observation.serial, observation.kind, observation.observed,
            observation.received, observation.event_id, observation.payload,
        ),
    ).rowcount
    if new_observation:
        return

    duplicates["semantic_retry_excess"] += 1
    if inserted:
        duplicates["new_id_alias_excess"] += 1

    prior = conn.execute(
        """
        SELECT rowid, received, event_id
        FROM events
        WHERE serial = ? AND kind = ? AND observed = ? AND payload = ?
        """,
        observation.identity,
    ).fetchone()
    receipt = observation.received
    if (receipt, observation.event_id) < (prior["received"], prior["event_id"]):
        conn.execute(
            "UPDATE events SET received = ?, event_id = ? WHERE rowid = ?",
            (receipt, observation.event_id, prior["rowid"]),
        )
        receipt = prior["received"]
    conn.execute(
        "INSERT INTO retry_receipts(observation_rowid, received) VALUES (?, ?)",
        (prior["rowid"], receipt),
    )


def _stream_history(conn: sqlite3.Connection, data: Path, devices: dict[str, dict]) -> dict:
    paths = sorted((data / "telemetry").glob("*.jsonl"))
    if not paths:
        raise FileNotFoundError(f"no replay JSONL files under {data / 'telemetry'}")
    counters = Counter({
        "envelopes": 0,
        "malformed_envelopes": 0,
        "ignored_unknown_types": 0,
        "receipt_order_inversions": 0,
        "receipt_day_mismatches": 0,
        "clock_ahead_envelopes": 0,
        "bx_without_outer_serial_or_device_time": 0,
    })
    by_type = Counter()
    formats = Counter()
    malformed_reasons = Counter()
    unknown_types = Counter()
    duplicates = Counter({
        "repeated_event_id_excess": 0,
        "semantic_retry_excess": 0,
        "new_id_alias_excess": 0,
        "conflicting_event_id_envelopes": 0,
    })
    unknown_serials = Counter()
    receipts_by_serial = Counter()
    hashes = {}
    files = {}
    previous_receipt = None

    for path in paths:
        digest = hashlib.sha256()
        rows = 0
        with path.open("rb") as stream:
            for line in stream:
                digest.update(line)
                if not line.strip():
                    continue
                rows += 1
                counters["envelopes"] += 1
                try:
                    raw = json.loads(line)
                    if not isinstance(raw, dict):
                        raise ValueError("envelope is not an object")
                    kind = required_text(raw.get("type"))
                    by_type[kind] += 1
                    if kind not in EVENT_FIELDS and kind != "bx_raw":
                        required_text(raw.get("event_id"))
                        parse_time(raw.get("received_at"))
                        counters["ignored_unknown_types"] += 1
                        unknown_types[kind] += 1
                        continue
                    event = _normalize_event(raw, devices)
                except (ValueError, OverflowError, OSError, RecursionError) as error:
                    counters["malformed_envelopes"] += 1
                    label = type(error).__name__ if isinstance(error, (json.JSONDecodeError, UnicodeDecodeError)) else str(error)
                    malformed_reasons[label] += 1
                    continue

                device = devices.get(event.serial)
                if device is None:
                    unknown_serials[event.serial] += 1
                family = device["family"] if device else "BX" if kind == "bx_raw" else "unknown"
                firmware = device["firmware"] or "unknown" if device else "unknown"
                formats[f"{family}/{firmware}/{event.time_format}"] += 1
                receipts_by_serial[event.serial] += 1

                if kind == "bx_raw" and "serial" not in raw and "device_time" not in raw:
                    counters["bx_without_outer_serial_or_device_time"] += 1
                if event.observed > event.received:
                    counters["clock_ahead_envelopes"] += 1
                if previous_receipt is not None and event.received < previous_receipt:
                    counters["receipt_order_inversions"] += 1
                previous_receipt = event.received
                if not raw["received_at"].startswith(path.stem + "T") or not raw["received_at"].endswith("Z"):
                    counters["receipt_day_mismatches"] += utc_text(event.received)[:10] != path.stem
                _store_event(conn, event, duplicates)

        relative = path.relative_to(data).as_posix()
        hashes[relative] = digest.hexdigest()
        files[relative] = rows
        conn.commit()

    duplicates["distinct_event_ids"] = conn.execute("SELECT COUNT(*) FROM event_ids").fetchone()[0]
    duplicates["logical_observations"] = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    duplicates["semantic_retry_groups"] = conn.execute(
        "SELECT COUNT(DISTINCT observation_rowid) FROM retry_receipts"
    ).fetchone()[0]
    return {
        **counters,
        "files": files,
        "envelopes_by_type": dict(by_type),
        "observation_formats_by_family_firmware": dict(formats),
        "malformed_reasons": dict(malformed_reasons),
        "unknown_types": dict(unknown_types),
        "unknown_serials": dict(unknown_serials),
        "duplicates": dict(duplicates),
        "receipt_counts_by_serial": receipts_by_serial,
        "hashes": hashes,
    }


def _quantiles(samples: Counter) -> dict:
    size = sum(samples.values())
    result = {"n": size}
    if not size:
        return result
    ordered = sorted(samples.items())
    result["min"] = ordered[0][0]
    result["max"] = ordered[-1][0]
    ranks = {f"p{pct}": math.ceil(size * pct / 100) for pct in (50, 90, 95, 99)}
    ranks["p99_lower"] = (size - 1) * 99 // 100 + 1
    for name, rank in ranks.items():
        for value, count in ordered:
            rank -= count
            if rank <= 0:
                result[name] = value
                break
    return result


def _event_profiles(conn: sqlite3.Connection, devices: dict[str, dict]) -> dict:
    delays = defaultdict(Counter)
    distinct_by_kind = Counter()
    bx_flags = Counter()
    for row in conn.execute("SELECT serial, kind, observed, received FROM events"):
        device = devices.get(row["serial"])
        kind = row["kind"]
        family = device["family"] if device else "BX" if kind == "bx_raw" else "unknown"
        firmware = device["firmware"] or "unknown" if device else "unknown"
        delay = row["received"] - row["observed"]
        if delay >= 0:
            delays[f"{family}/{firmware}"][delay] += 1
        distinct_by_kind[kind] += 1
    for row in conn.execute("SELECT payload FROM events WHERE kind = 'bx_raw'"):
        bx_flags[str(json.loads(row["payload"])["unknown_flags"])] += 1
    retry_lags = Counter(
        row[0] for row in conn.execute(
            """
            SELECT r.received - e.received
            FROM retry_receipts AS r JOIN events AS e ON e.rowid = r.observation_rowid
            """
        )
    )
    return {
        "logical_observations_by_type": dict(distinct_by_kind),
        "receipt_lag_seconds": {cohort: _quantiles(values) for cohort, values in delays.items()},
        "semantic_retry_receipt_delay_seconds": _quantiles(retry_lags),
        "bx_unknown_flag_values": dict(bx_flags),
    }


@contextmanager
def open_dataset(data: Path) -> Iterator[tuple[sqlite3.Connection, dict, dict]]:
    """Yield a temporary SQLite observation table, reference rows, and audit report."""
    data = Path(data)
    references, summaries, hashes = _load_references(data)
    devices = {row["serial"]: row for row in references["devices"]}
    with tempfile.TemporaryDirectory(prefix="quiet-fleet-audit-") as temporary:
        conn = sqlite3.connect(Path(temporary) / "history.sqlite3")
        conn.row_factory = sqlite3.Row
        try:
            # This database is disposable. Input files remain untouched.
            conn.executescript(
                "PRAGMA journal_mode=OFF; PRAGMA synchronous=OFF; PRAGMA cache_size=-65536;"
                + CREATE_SCHEMA
            )
            telemetry = _stream_history(conn, data, devices)
            hashes.update(telemetry.pop("hashes"))
            receipt_counts = telemetry.pop("receipt_counts_by_serial")
            conn.executescript(
                """
                CREATE INDEX events_kind_serial_observed ON events(kind, serial, observed);
                CREATE INDEX events_received ON events(received);
                """
            )
            telemetry.update(_event_profiles(conn, devices))
            audit = {
                "schema_version": 1,
                "methodology": {
                    "stream_order": "lexical daily filename then physical line order",
                    "logical_identity": "serial, event kind, normalized observation instant, canonical payload",
                    "representative_receipt": "minimum (receipt Unix seconds, original event ID)",
                    "receipt_lag": "representative receipt minus observation, in seconds, excluding clocks ahead of receipt",
                    "quantiles": "nearest rank, with p99_lower for comparison to the lower order statistic",
                    "camera_case_firmware": "firmware mentioned in case notes, falling back to the reference roster",
                    "seasonal_activity": "last observed A or BX report on current reference trailer assignments, by local depot date",
                },
                "sources_sha256": hashes,
                "references": summaries,
                "telemetry": telemetry,
                "support_cases": _case_audit(references["support_cases"], devices),
                "vin_assignments": _vin_audit(conn, references["assets"], devices, receipt_counts),
                "seasonal_activity": _seasonal_audit(conn, references["assets"], devices),
                "plan_changes": _plan_audit(conn, references["plan_changes"]),
            }
            yield conn, references, audit
        finally:
            conn.close()


def _case_audit(cases: list[dict], devices: dict[str, dict]) -> dict:
    causes = Counter()
    actions_by_cause = defaultdict(Counter)
    outcomes_by_cause = defaultdict(Counter)
    camera_firmware_actions = defaultdict(Counter)
    invalid_durations = []
    for row in cases:
        cause = row["root_cause"]
        causes[cause] += 1
        actions_by_cause[cause][row["action"]] += 1
        outcomes_by_cause[cause][row["outcome"]] += 1
        try:
            start, _ = parse_time(row["opened_at"])
            end, _ = parse_time(row["closed_at"])
        except ValueError:
            invalid_durations.append({
                "case_id": row["case_id"], "reason": "unusable opened_at or closed_at"
            })
        else:
            if end < start:
                invalid_durations.append({
                    "case_id": row["case_id"],
                    "opened_at": row["opened_at"],
                    "closed_at": row["closed_at"],
                    "duration_seconds": end - start,
                })
        if cause == "camera_fault":
            match = re.search(r"\bfirmware\s+(\d+\.\d+\.\d+)\b", row["notes"], re.IGNORECASE)
            firmware = match[1] if match else devices.get(row["serial"], {}).get("firmware", "")
            camera_firmware_actions[firmware or "unknown"][row["action"]] += 1
    return {
        "by_cause": dict(causes),
        "actions_by_cause": {cause: dict(actions) for cause, actions in actions_by_cause.items()},
        "outcomes_by_cause": {cause: dict(outcomes) for cause, outcomes in outcomes_by_cause.items()},
        "camera_actions_by_firmware": {
            firmware: dict(actions) for firmware, actions in camera_firmware_actions.items()
        },
        "invalid_durations": invalid_durations,
    }


def _vin_audit(
    conn: sqlite3.Connection, assets: list[dict], devices: dict[str, dict], receipt_counts: Counter
) -> dict:
    owners_by_vin = defaultdict(list)
    for asset in assets:
        if asset["vin"]:
            owners_by_vin[asset["vin"]].append(asset["asset_id"])
    rows_by_vin = defaultdict(list)
    seen_serials = set()
    roster_mismatches = []
    for row in conn.execute(
        """
        SELECT serial, json_extract(payload, '$.vin') AS vin,
               MIN(observed) AS first_time, MAX(observed) AS last_time,
               MIN(received) AS first_received, COUNT(*) AS n
        FROM events
        WHERE kind IN ('heartbeat', 'ignition_on') AND observed <= received
        GROUP BY serial, vin
        ORDER BY vin, first_time, serial
        """
    ):
        vin = row["vin"]
        if not isinstance(vin, str) or not vin:
            continue
        serial = row["serial"]
        seen_serials.add(serial)
        candidate_assets = owners_by_vin.get(vin, [])
        device = devices.get(serial, {})
        roster_asset = device.get("asset_id", "")
        finding = {
            "serial": serial,
            "vin": vin,
            "asset_candidates": candidate_assets,
            "roster_asset_id": roster_asset or None,
            "roster_status": device.get("status"),
            "roster_installed_at": device.get("installed_at") or None,
            "first_observed": utc_text(row["first_time"]),
            "first_received": utc_text(row["first_received"]),
            "last_observed": utc_text(row["last_time"]),
            "vin_observations": row["n"],
            "raw_envelopes": receipt_counts[serial],
        }
        rows_by_vin[vin].append(finding)
        if len(candidate_assets) != 1 or roster_asset not in candidate_assets:
            roster_mismatches.append(finding)
    return {
        "distinct_nonblank_asset_vins": len(owners_by_vin),
        "ambiguous_asset_vins": {
            vin: candidates for vin, candidates in owners_by_vin.items() if len(candidates) > 1
        },
        "serials_with_vin_observations": len(seen_serials),
        "roster_mismatches": roster_mismatches,
        "shared_vin_serial_timelines": [rows for rows in rows_by_vin.values() if len(rows) > 1],
    }


def _seasonal_audit(conn: sqlite3.Connection, assets: list[dict], devices: dict[str, dict]) -> dict:
    last_by_serial = {
        row["serial"]: row["last_time"]
        for row in conn.execute(
            """
            SELECT serial, MAX(observed) AS last_time
            FROM events
            WHERE kind IN ('check_in', 'bx_raw') AND observed <= received
            GROUP BY serial
            """
        )
    }
    devices_by_asset = defaultdict(list)
    for device in devices.values():
        if device["family"] in ("A", "BX"):
            devices_by_asset[device["asset_id"]].append(device["serial"])
    dates_by_use = defaultdict(Counter)
    landscaping = []
    for asset in assets:
        if asset["type"] != "trailer" or asset["depot"] not in ZONES:
            continue
        serials = devices_by_asset[asset["asset_id"]]
        last = max((last_by_serial[serial] for serial in serials if serial in last_by_serial), default=None)
        zone = ZoneInfo(ZONES[asset["depot"]])
        local_day = datetime.fromtimestamp(last, zone).date().isoformat() if last is not None else None
        dates_by_use[asset["use"]][local_day or "no_observation"] += 1
        if asset["use"] == "landscaping":
            landscaping.append({
                "asset_id": asset["asset_id"],
                "depot": asset["depot"],
                "local_last_report_date": local_day,
                "last_observed": utc_text(last) if last is not None else None,
            })
    return {
        "last_local_report_date_by_trailer_use": {
            use: dict(dates) for use, dates in dates_by_use.items()
        },
        "landscaping_trailers": landscaping,
    }


def _plan_audit(conn: sqlite3.Connection, rows: list[dict]) -> dict:
    reference = {row["event_id"]: row for row in rows}
    stream = {row["event_id"]: row for row in conn.execute("SELECT * FROM events WHERE kind = 'plan_change'")}
    differing = []
    for event_id in sorted(reference.keys() & stream.keys()):
        csv_row = reference[event_id]
        event = stream[event_id]
        expected = {key: csv_row[key] for key in ("plan", "status", "reason")}
        if (
            event["serial"] != csv_row["serial"]
            or event["observed"] != parse_time(csv_row["time"])[0]
            or json.loads(event["payload"]) != expected
        ):
            differing.append(event_id)
    return {
        "reference_events": len(reference),
        "stream_events": len(stream),
        "reference_only_ids": sorted(reference.keys() - stream.keys()),
        "stream_only_ids": sorted(stream.keys() - reference.keys()),
        "field_mismatch_ids": differing,
        "reference_status_counts": dict(Counter(row["status"] for row in rows)),
    }


def audit_bx_examples(bx_dir: Path) -> dict:
    sample_path = bx_dir / "bx_raw_messages.txt"
    portal_path = bx_dir / "portal_readout.csv"
    with portal_path.open(newline="", encoding="utf-8") as stream:
        anchors = list(csv.DictReader(stream))
    indexed_anchors = {}
    for row in anchors:
        displayed_at = datetime.strptime(row["last_report_portal_time"], "%Y-%m-%d %H:%M:%S")
        observed = displayed_at.replace(tzinfo=ZoneInfo(ZONES["REG"])).timestamp()
        indexed_anchors[(row["unit"], observed)] = row
    decoded_anchors = {}
    serials = set()
    total = 0
    flags = Counter()
    with sample_path.open(encoding="utf-8") as stream:
        for line in stream:
            if not line.strip():
                continue
            total += 1
            serial, observed, values = decode_bx(line)
            serials.add(serial)
            flags[str(values["unknown_flags"])] += 1
            portal = indexed_anchors.get((serial, observed))
            if portal is None:
                continue
            display = {
                "last_report_portal_time": datetime.fromtimestamp(
                    observed, ZoneInfo(ZONES["REG"])
                ).strftime("%Y-%m-%d %H:%M:%S"),
                "battery": f"{math.floor(values['battery_pct'] + 0.5)}%",
                "moving": "Yes" if values["moving"] else "No",
                "low_battery": "Yes" if values["low_battery"] else "No",
                "gps_fix": "Yes" if values["gps_fix"] else "No",
                "latitude": f"{values['lat']:.5f}",
                "longitude": f"{values['lng']:.5f}",
            }
            decoded_anchors[(serial, observed)] = {
                "serial": serial,
                "observed_utc": utc_text(observed),
                "display": display,
                "all_fields_match": all(display[key] == portal[key] for key in display),
            }
    return {
        "sources_sha256": {path.name: _hash_file(path) for path in (sample_path, portal_path)},
        "sample_messages": total,
        "sample_serials": len(serials),
        "unknown_flag_values": dict(flags),
        "anchors_expected": len(anchors),
        "anchors_matching": sum(row["all_fields_match"] for row in decoded_anchors.values()),
        "anchors": [decoded_anchors[key] for key in sorted(decoded_anchors)],
    }


def _text_counts(counts: dict) -> str:
    return ", ".join(f"{key} ({value:,})" for key, value in sorted(counts.items())) or "none"


def render_markdown(audit: dict) -> str:
    telemetry = audit["telemetry"]
    duplicates = telemetry["duplicates"]
    retry = telemetry["semantic_retry_receipt_delay_seconds"]
    notes = [
        "# Data quality audit",
        "",
        "Regenerate locally with `python3.12 scripts/audit_data.py --data data`. "
        "The [JSON report](../reports/data-audit.json) includes all file hashes, headers, "
        "blank counts, references, cohort sizes, and the supporting aggregates.",
        "",
        "## Reference and stream checks",
        "",
        "| Reference table | Rows | Duplicate primary key excess |",
        "|---|---:|---:|",
    ]
    for name, row in audit["references"].items():
        notes.append(f"| `{name}.csv` | {row['rows']:,} | {row['duplicate_primary_key_excess']:,} |")
    notes += [
        "",
        f"Device families are {_text_counts(audit['references']['devices']['by_family'])}. "
        f"Roster statuses are {_text_counts(audit['references']['devices']['by_status'])}. "
        "Blank VINs and assignments occur in different cohorts. An empty roster assignment "
        "cannot rule out observed operation.",
        "",
        f"The audit scanned {len(telemetry['files'])} daily files and {telemetry['envelopes']:,} "
        f"nonblank envelopes. It found {telemetry['malformed_envelopes']:,} malformed envelopes, "
        f"{telemetry['ignored_unknown_types']:,} ignored unknown types and "
        f"{len(telemetry['unknown_serials']):,} distinct unresolved serials. "
        f"The audit found {telemetry['clock_ahead_envelopes']:,} observations ahead of receipt, "
        f"{telemetry['receipt_order_inversions']:,} receipt inversions, and "
        f"{telemetry['receipt_day_mismatches']:,} receipt-day mismatches.",
        "",
        f"The stream and CSV contain {audit['plan_changes']['stream_events']:,} and "
        f"{audit['plan_changes']['reference_events']:,} plan event IDs respectively. "
        f"The report records {len(audit['plan_changes']['reference_only_ids']):,} reference-only, "
        f"{len(audit['plan_changes']['stream_only_ids']):,} stream-only, and "
        f"{len(audit['plan_changes']['field_mismatch_ids']):,} matched-ID field disagreements. "
        "The reference has no independent receipt timestamp.",
        "",
        "## Identity, clocks and buffering",
        "",
        f"Known and decodable envelopes yield {duplicates['distinct_event_ids']:,} distinct IDs "
        f"and {duplicates['logical_observations']:,} logical observations. There are "
        f"{duplicates['repeated_event_id_excess']:,} repeated IDs, "
        f"{duplicates['semantic_retry_excess']:,} semantic retries across "
        f"{duplicates['semantic_retry_groups']:,} groups, and "
        f"{duplicates['new_id_alias_excess']:,} new-ID aliases. There are "
        f"{duplicates['conflicting_event_id_envelopes']:,} conflicting-ID envelopes.",
        "",
        "The semantic key uses serial, kind, normalized observation instant and sorted canonical "
        "payload. The audit retains the lowest receipt for the logical observation, breaking ties "
        "by event ID. The first valid content wins a conflicting ID. The audit counts aliases after "
        "validating relevant envelopes and ignores unused kinds. Latency is first receipt minus "
        "observation, excluding ahead-of-receipt clocks. Quantiles are nearest rank.",
        "",
        "| Family / firmware | Observations | Median lag (s) | P99 lag (s) | Max lag (s) |",
        "|---|---:|---:|---:|---:|",
    ]
    for cohort, row in sorted(telemetry["receipt_lag_seconds"].items()):
        notes.append(f"| {cohort} | {row['n']:,} | {row['p50']:g} | {row['p99']:g} | {row['max']:g} |")
    notes.append("")
    for cohort, row in sorted(telemetry["receipt_lag_seconds"].items()):
        if row["p99_lower"] != row["p99"]:
            notes += [
                f"For {cohort}, the lower order statistic used by the kit gives p99 "
                f"{row['p99_lower']:g} s on the same {row['n']:,} observations. "
                f"The table uses nearest rank at {row['p99']:g} s.",
                "",
            ]
    if retry["n"]:
        notes += [
            f"Across {retry['n']:,} retry receipts, receipt-to-first-receipt lag has a median "
            f"of {retry['p50']:g} s and a maximum of {retry['max']:g} s. Long tracker delivery "
            "tails are compatible with buffering. Receipt lag measures delivery, and calibration "
            "uses a separate observation cadence calculation.",
            "",
        ]
    numeric_count = sum(
        count for cohort, count in telemetry["observation_formats_by_family_firmware"].items()
        if cohort.endswith("/epoch_seconds")
    )
    notes += [
        f"The stream contains {numeric_count:,} legacy A numeric-clock envelopes. "
        f"There are {telemetry['bx_without_outer_serial_or_device_time']:,} BX envelopes without "
        f"outer serial or device time and {telemetry['logical_observations_by_type'].get('bx_raw', 0):,} "
        "logical BX observations. BX timestamps are hex epoch seconds.",
        "",
        "## VIN and seasonal patterns",
        "",
    ]
    vin_info = audit["vin_assignments"]
    notes += [
        f"The audit found {vin_info['distinct_nonblank_asset_vins']:,} distinct known asset VINs, "
        f"{len(vin_info['shared_vin_serial_timelines']):,} shared VIN timelines. "
        f"Flagged serial/VIN associations number {len(vin_info['roster_mismatches']):,}. "
        "Flagged associations disagree with the roster or need a unique reference VIN. The JSON "
        "preserves the observed time bounds. "
        "Historical assignment requires evidence available at the query cutoff.",
        "",
    ]
    for row in vin_info["roster_mismatches"]:
        if row["roster_status"] == "stock" and len(row["asset_candidates"]) == 1:
            notes.append(
                f"- Stock serial `{row['serial']}` has {row['raw_envelopes']:,} envelopes and "
                f"first reports the known VIN of `{row['asset_candidates'][0]}` at {row['first_observed']}."
            )
    if notes[-1]:
        notes.append("")
    seasonal = audit["seasonal_activity"]["landscaping_trailers"]
    dates = Counter(row["local_last_report_date"] or "no observation" for row in seasonal)
    notes += [
        f"Landscaping trailers number {len(seasonal):,}. Their last local observation dates are "
        f"{_text_counts(dates)}. This pattern leaves approved downtime scope and dates unresolved.",
        "",
        "## Selected support cases",
        "",
        f"Case counts by cause are {_text_counts(audit['support_cases']['by_cause'])}. "
        "The case rows represent selected reports and fixes. Their mix can support a prior "
        "or case-aligned evaluation. It provides no fleet-wide error denominator.",
        "",
        "| Camera fault firmware | Cases | Actions |",
        "|---|---:|---|",
    ]
    for firmware, actions in sorted(audit["support_cases"]["camera_actions_by_firmware"].items()):
        notes.append(f"| {firmware} | {sum(actions.values()):,} | {_text_counts(actions)} |")
    invalid = audit["support_cases"]["invalid_durations"]
    notes += [
        "",
        f"The duration analysis excludes {len(invalid):,} flagged case rows. "
        f"Flagged case IDs are {', '.join(row['case_id'] for row in invalid) or 'none'}.",
        "",
    ]
    if "bx_examples" in audit:
        bx = audit["bx_examples"]
        notes += [
            "## BX reference comparison",
            "",
            f"Decoded {bx['sample_messages']:,} separate sample frames from "
            f"{bx['sample_serials']:,} serials and matched {bx['anchors_matching']:,} of "
            f"{bx['anchors_expected']:,} supplied portal rows across every displayed field. "
            "Battery full-scale conversion is an inference from rounded examples. "
            f"Unknown flag values and counts are {_text_counts(bx['unknown_flag_values'])}.",
            "",
        ]
    return "\n".join(notes)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=ROOT / "data")
    parser.add_argument("--reports-dir", type=Path, default=ROOT / "reports")
    parser.add_argument("--docs-dir", type=Path, default=ROOT / "docs")
    parser.add_argument("--bx-dir", type=Path, default=ROOT / "vendor/quiet-fleet/new_hardware")
    args = parser.parse_args()

    with open_dataset(args.data) as (_, _, report):
        report["bx_examples"] = audit_bx_examples(args.bx_dir)

    args.reports_dir.mkdir(parents=True, exist_ok=True)
    args.docs_dir.mkdir(parents=True, exist_ok=True)
    report_path = args.reports_dir / "data-audit.json"
    doc_path = args.docs_dir / "data-quality.md"
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    doc_path.write_text(render_markdown(report), encoding="utf-8")
    print(f"Audited {report['telemetry']['envelopes']:,} envelopes")
    print(f"Wrote {report_path} and {doc_path}")


if __name__ == "__main__":
    main()
