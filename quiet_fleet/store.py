"""Store logical observations and original receipts in a temporary SQLite database."""

from __future__ import annotations

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
        with self._lock:
            rows = self._connection.execute(
                """
                SELECT event_id, serial, kind, raw_type, first_received_us, observed_us,
                       device_origin, time_quality, payload_json, raw_device_time_json
                FROM messages
                WHERE serial IS ? AND first_received_us <= ?
                ORDER BY observed_us NULLS LAST, first_received_us, event_id
                """,
                (serial, at_us),
            ).fetchall()
        return tuple(
            EventFact(
                event_id, fact_serial, kind, raw_type, received, observed,
                bool(device_origin), time_quality, payload, raw_device_time,
            )
            for (
                event_id, fact_serial, kind, raw_type, received, observed,
                device_origin, time_quality, payload, raw_device_time,
            ) in rows
        )

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
