"""Manage a fresh local database for each application lifespan."""

import sqlite3
from collections.abc import Iterator
from contextlib import closing, contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory


@contextmanager
def open_store() -> Iterator[sqlite3.Connection]:
    with TemporaryDirectory(prefix="quiet-fleet-") as directory:
        path = Path(directory) / "telemetry.sqlite3"
        with closing(sqlite3.connect(path, check_same_thread=False)) as connection:
            yield connection
