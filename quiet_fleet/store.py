"""Store logical observations and original receipts in a temporary SQLite database."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator, Sequence
from contextlib import closing, contextmanager
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Lock
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .normalize import NormalizedEvent


_SCHEMA = """
CREATE TABLE messages (
    fingerprint BLOB PRIMARY KEY,
    serial TEXT,
    kind TEXT NOT NULL,
    raw_type TEXT NOT NULL,
    observed_us INTEGER,
    device_origin INTEGER NOT NULL,
    payload_json TEXT NOT NULL,
    event_id TEXT NOT NULL,
    first_received_us INTEGER NOT NULL,
    time_quality TEXT NOT NULL,
    raw_device_time_json TEXT,
    representative_hash BLOB NOT NULL
) WITHOUT ROWID;

CREATE TABLE event_ids (
    event_id TEXT PRIMARY KEY,
    fingerprint BLOB NOT NULL REFERENCES messages(fingerprint) DEFERRABLE INITIALLY DEFERRED
) WITHOUT ROWID;

CREATE TABLE receipts (
    event_id TEXT NOT NULL REFERENCES event_ids(event_id),
    received_us INTEGER NOT NULL,
    envelope_hash BLOB NOT NULL,
    raw_device_time_json TEXT,
    PRIMARY KEY (event_id, received_us)
) WITHOUT ROWID;

CREATE INDEX message_receipt_by_serial ON messages (serial, first_received_us);
CREATE INDEX message_observation_by_kind ON messages (kind, serial, observed_us);
CREATE INDEX message_vin_claim ON messages (json_extract(payload_json, '$.vin'), serial)
    WHERE kind IN ('heartbeat', 'ignition_on');
CREATE INDEX event_ids_by_message ON event_ids (fingerprint);
"""

_INSERT_MESSAGE = """
INSERT INTO messages (
    fingerprint, serial, kind, raw_type, observed_us, device_origin,
    payload_json, event_id, first_received_us, time_quality, raw_device_time_json, representative_hash
)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT (fingerprint) DO NOTHING
"""

_UPDATE_REPRESENTATIVE = """
UPDATE messages SET
    event_id = ?,
    first_received_us = ?,
    time_quality = ?,
    raw_device_time_json = ?,
    representative_hash = ?
WHERE fingerprint = ?
    AND (?, ?, ?) < (first_received_us, event_id, representative_hash)
"""

_FACT_FIELDS = """
event_id, serial, kind, raw_type, first_received_us, observed_us,
device_origin, time_quality, payload_json, raw_device_time_json
"""
_CREDIBLE_AT = """
first_received_us <= :at_us AND observed_us <= :at_us
AND time_quality = 'credible' AND device_origin = 1
"""
_VIN_CLAIM = """
kind IN ('heartbeat', 'ignition_on')
AND json_type(payload_json, '$.vin') = 'text'
AND json_extract(payload_json, '$.vin') <> ''
"""


@dataclass(frozen=True, slots=True)
class EventFact:
    event_id: str
    serial: str | None
    kind: str
    raw_type: str
    first_received_us: int
    observed_us: int | None
    device_origin: bool
    time_quality: str
    payload_json: str
    raw_device_time_json: str | None


@dataclass(frozen=True, slots=True)
class Receipt:
    event_id: str
    received_us: int
    envelope_hash: bytes
    raw_device_time_json: str | None


@dataclass(frozen=True, slots=True)
class BatchWriteResult:
    accepted: int
    inserted: int
    conflicts: int


@dataclass(frozen=True, slots=True)
class StoreCounts:
    messages: int
    original_ids: int
    receipts: int
    conflicts: int


def _fact(row: tuple) -> EventFact:
    event_id, serial, kind, raw_type, received, observed, origin, quality, payload, raw_time = row
    return EventFact(event_id, serial, kind, raw_type, received, observed, bool(origin), quality, payload, raw_time)


class ReadSnapshot:
    """Read selected facts at one cutoff while the store's write lock is held."""

    def __init__(self, connection: sqlite3.Connection, at_us: int) -> None:
        self._connection: sqlite3.Connection | None = connection
        self._at_us = at_us

    def _query(self, sql: str, **parameters: str | None) -> sqlite3.Cursor:
        if self._connection is None:
            raise RuntimeError("The read snapshot has closed")
        return self._connection.execute(sql, {"at_us": self._at_us, **parameters})

    def facts_for(self, serial: str | None) -> tuple[EventFact, ...]:
        rows = self._query(
            f"""
            SELECT {_FACT_FIELDS} FROM messages
            WHERE serial IS :serial AND first_received_us <= :at_us
            ORDER BY observed_us NULLS LAST, first_received_us, event_id
            """,
            serial=serial,
        )
        return tuple(_fact(row) for row in rows)

    def related_vin_claims(self, vin: str | None, roster_serials: tuple[str, ...]) -> tuple[EventFact, ...]:
        """Find eligible VIN claims for a target asset's observed and recorded trackers."""
        rows = self._query(
            f"""
            WITH related(serial) AS (
                SELECT value FROM json_each(:roster_serials)
                UNION
                SELECT serial FROM messages
                WHERE kind IN ('heartbeat', 'ignition_on')
                      AND json_extract(payload_json, '$.vin') = :vin
                      AND {_CREDIBLE_AT} AND serial IS NOT NULL
            ), ranked AS (
                SELECT {_FACT_FIELDS},
                       DENSE_RANK() OVER (PARTITION BY serial ORDER BY observed_us DESC) AS age_rank
                FROM messages
                WHERE {_VIN_CLAIM} AND {_CREDIBLE_AT} AND serial IS NOT NULL
                      AND serial IN (SELECT serial FROM related)
            )
            SELECT {_FACT_FIELDS} FROM ranked WHERE age_rank = 1
            ORDER BY serial, first_received_us, event_id
            """,
            vin=vin,
            roster_serials=json.dumps(roster_serials),
        )
        return tuple(_fact(row) for row in rows)

    def latest_measurement(self, serial: str) -> EventFact | None:
        row = self._query(
            f"""
            SELECT {_FACT_FIELDS} FROM messages
            WHERE serial = :serial AND {_CREDIBLE_AT}
            ORDER BY observed_us DESC, first_received_us DESC, event_id DESC LIMIT 1
            """,
            serial=serial,
        ).fetchone()
        return _fact(row) if row is not None else None

    def first_vin_claim(self, serial: str, vin: str) -> EventFact | None:
        row = self._query(
            f"""
            SELECT {_FACT_FIELDS} FROM messages
            WHERE serial = :serial AND {_VIN_CLAIM} AND {_CREDIBLE_AT}
                  AND json_extract(payload_json, '$.vin') = :vin
            ORDER BY observed_us, first_received_us, event_id LIMIT 1
            """,
            serial=serial,
            vin=vin,
        ).fetchone()
        return _fact(row) if row is not None else None


class EventStore:
    """Serialize writes and reads on one connection owned by the process lifespan."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection
        self._lock = Lock()
        self._conflicts = 0

    def write_batch(self, events: Sequence[NormalizedEvent]) -> BatchWriteResult:
        """Commit accepted normalized events together, counting retries as accepted."""
        inserted = 0
        conflicts = 0
        with self._lock:
            with self._connection:
                for event in events:
                    new_messages = self._write_event(event)
                    if new_messages is None:
                        conflicts += 1
                    else:
                        inserted += new_messages
            self._conflicts += conflicts
        return BatchWriteResult(accepted=len(events) - conflicts, inserted=inserted, conflicts=conflicts)

    def _write_event(self, event: NormalizedEvent) -> int | None:
        connection = self._connection
        bound = connection.execute(
            """
            INSERT INTO event_ids (event_id, fingerprint) VALUES (?, ?)
            ON CONFLICT (event_id) DO NOTHING
            """,
            (event.event_id, event.fingerprint),
        ).rowcount
        if not bound:
            (existing_fingerprint,) = connection.execute(
                "SELECT fingerprint FROM event_ids WHERE event_id = ?", (event.event_id,)
            ).fetchone()
            if existing_fingerprint != event.fingerprint:
                return None

        inserted = connection.execute(
            _INSERT_MESSAGE,
            (
                event.fingerprint, event.serial, event.kind, event.raw_type, event.observed_us,
                event.device_origin, event.payload_json, event.event_id, event.received_us,
                event.time_quality, event.raw_device_time_json, event.envelope_hash,
            ),
        ).rowcount
        if not inserted:
            # Only an earlier known receipt can replace the representative or its time quality.
            # Original ID breaks receipt-time ties, and the hash settles equivalent raw encodings.
            connection.execute(
                _UPDATE_REPRESENTATIVE,
                (
                    event.event_id, event.received_us, event.time_quality, event.raw_device_time_json,
                    event.envelope_hash, event.fingerprint, event.received_us, event.event_id,
                    event.envelope_hash,
                ),
            )

        connection.execute(
            """
            INSERT INTO receipts (event_id, received_us, envelope_hash, raw_device_time_json)
            VALUES (?, ?, ?, ?)
            ON CONFLICT (event_id, received_us) DO UPDATE SET
                envelope_hash = excluded.envelope_hash,
                raw_device_time_json = excluded.raw_device_time_json
            WHERE excluded.envelope_hash < receipts.envelope_hash
            """,
            (event.event_id, event.received_us, event.envelope_hash, event.raw_device_time_json),
        )
        return inserted

    def snapshot(self, at_us: int, serial: str | None) -> tuple[EventFact, ...]:
        """Return eligible facts for one serial, or for opaque observations when serial is None."""
        with self.read_snapshot(at_us) as snapshot:
            return snapshot.facts_for(serial)

    @contextmanager
    def read_snapshot(self, at_us: int) -> Iterator[ReadSnapshot]:
        """Keep related serial reads on the same committed view of the event store."""
        with self._lock:
            snapshot = ReadSnapshot(self._connection, at_us)
            try:
                yield snapshot
            finally:
                snapshot._connection = None

    def receipts_for(self, event_id: str, at_us: int) -> tuple[Receipt, ...]:
        """Return original receipts visible for the logical message represented by an ID."""
        with self._lock:
            rows = self._connection.execute(
                """
                SELECT receipts.event_id, receipts.received_us, receipts.envelope_hash,
                       receipts.raw_device_time_json
                FROM event_ids
                JOIN receipts USING (event_id)
                WHERE event_ids.fingerprint = (
                    SELECT fingerprint FROM event_ids WHERE event_id = ?
                ) AND receipts.received_us <= ?
                ORDER BY receipts.received_us, receipts.event_id
                """,
                (event_id, at_us),
            ).fetchall()
        return tuple(Receipt(*row) for row in rows)

    def counts(self) -> StoreCounts:
        with self._lock:
            messages, original_ids, receipts = self._connection.execute(
                """
                SELECT (SELECT COUNT(*) FROM messages),
                       (SELECT COUNT(*) FROM event_ids),
                       (SELECT COUNT(*) FROM receipts)
                """
            ).fetchone()
            return StoreCounts(messages, original_ids, receipts, self._conflicts)


@contextmanager
def open_store() -> Iterator[EventStore]:
    with TemporaryDirectory(prefix="quiet-fleet-") as directory:
        path = Path(directory) / "telemetry.sqlite3"
        with closing(sqlite3.connect(path, check_same_thread=False)) as connection:
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute("PRAGMA synchronous = NORMAL")
            connection.executescript(_SCHEMA)
            yield EventStore(connection)
