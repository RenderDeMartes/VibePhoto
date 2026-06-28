"""SQLite connection management for a catalog.

Wraps one SQLite connection configured for catalog use (WAL journaling, enforced
foreign keys, row access by name) and serialises all access behind a reentrant
lock. SQLite's WAL mode allows many readers with a single writer; serialising
through one guarded connection is the simplest implementation of the
"single-writer" rule from ``docs/05`` and eliminates ``database is locked``
races between the indexer (worker threads) and the UI (GUI thread).

The public surface (``transaction``, ``execute``, ``executemany``, ``query``,
``query_one``) is deliberately small and storage-agnostic, so a later
optimisation to a dedicated writer thread + read-connection pool can land without
changing repository code.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from vibephoto.catalog.schema import migrate

logger = logging.getLogger(__name__)

#: SQLite parameter sequence type.
Params = Sequence[Any]


class Database:
    """A migrated, serialised SQLite connection for one catalog file."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._lock = threading.RLock()
        self._conn = self._connect()
        with self._lock:
            version = migrate(self._conn)
        logger.info("Opened catalog %s (schema v%d)", self.path.name, version)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(
            self.path,
            check_same_thread=False,  # access is externally serialised by _lock
            isolation_level=None,  # autocommit; explicit txns via `transaction`
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """Run a unit of work atomically: commit on success, rollback on error."""
        with self._lock:
            try:
                self._conn.execute("BEGIN")
                yield self._conn
                self._conn.execute("COMMIT")
            except Exception:
                self._conn.execute("ROLLBACK")
                raise

    def execute(self, sql: str, params: Params = ()) -> sqlite3.Cursor:
        """Execute a single write/DDL statement and return the cursor."""
        with self._lock:
            return self._conn.execute(sql, params)

    def executemany(self, sql: str, seq_params: Sequence[Params]) -> sqlite3.Cursor:
        """Execute a statement repeatedly over a sequence of parameter rows."""
        with self._lock:
            return self._conn.executemany(sql, seq_params)

    def query(self, sql: str, params: Params = ()) -> list[sqlite3.Row]:
        """Run a SELECT and return all rows."""
        with self._lock:
            return self._conn.execute(sql, params).fetchall()

    def query_one(self, sql: str, params: Params = ()) -> sqlite3.Row | None:
        """Run a SELECT and return the first row, or ``None``."""
        with self._lock:
            row: sqlite3.Row | None = self._conn.execute(sql, params).fetchone()
            return row

    def checkpoint(self) -> None:
        """Flush the WAL into the main database file (used before backups)."""
        with self._lock:
            self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")

    def integrity_ok(self) -> bool:
        """Return True if ``PRAGMA integrity_check`` reports no corruption."""
        row = self.query_one("PRAGMA integrity_check")
        return row is not None and row[0] == "ok"

    def optimize(self) -> None:
        """Refresh query-planner stats and reclaim space."""
        with self._lock:
            self._conn.execute("ANALYZE")
            self._conn.execute("VACUUM")

    def close(self) -> None:
        """Checkpoint and close the connection. Safe to call more than once."""
        with self._lock:
            if self._conn is not None:
                try:
                    self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                finally:
                    self._conn.close()
                    self._conn = None  # type: ignore[assignment]
