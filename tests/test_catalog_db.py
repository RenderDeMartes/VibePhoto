"""Tests for the catalog database layer: migrations, connection, transactions."""

from __future__ import annotations

from pathlib import Path

import pytest

from vibephoto.catalog.database import Database
from vibephoto.catalog.schema import SCHEMA_VERSION


def test_new_database_is_migrated(tmp_path: Path) -> None:
    db = Database(tmp_path / "c.vibephoto")
    version = db.query_one("PRAGMA user_version")
    assert version is not None and version[0] == SCHEMA_VERSION
    # Core tables exist.
    names = {r["name"] for r in db.query("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"photos", "folders", "metadata", "collections"} <= names
    db.close()


def test_wal_and_foreign_keys_enabled(tmp_path: Path) -> None:
    db = Database(tmp_path / "c.vibephoto")
    assert db.query_one("PRAGMA journal_mode")[0].lower() == "wal"
    assert db.query_one("PRAGMA foreign_keys")[0] == 1
    db.close()


def test_migration_is_idempotent(tmp_path: Path) -> None:
    path = tmp_path / "c.vibephoto"
    Database(path).close()
    db = Database(path)  # re-open: migrate() should be a no-op
    assert db.query_one("PRAGMA user_version")[0] == SCHEMA_VERSION
    db.close()


def test_transaction_commits(tmp_path: Path) -> None:
    db = Database(tmp_path / "c.vibephoto")
    db.execute("INSERT INTO volumes (uuid, label) VALUES ('v1', 'X')")
    with db.transaction():
        db.execute("INSERT INTO volumes (uuid, label) VALUES ('v2', 'Y')")
    assert len(db.query("SELECT * FROM volumes")) == 2
    db.close()


def test_transaction_rolls_back_on_error(tmp_path: Path) -> None:
    db = Database(tmp_path / "c.vibephoto")
    db.execute("INSERT INTO volumes (uuid, label) VALUES ('v1', 'X')")
    with pytest.raises(RuntimeError), db.transaction():
        db.execute("INSERT INTO volumes (uuid, label) VALUES ('v2', 'Y')")
        raise RuntimeError("boom")
    # The v2 insert was rolled back.
    assert len(db.query("SELECT * FROM volumes")) == 1
    db.close()


def test_integrity_check_ok(tmp_path: Path) -> None:
    db = Database(tmp_path / "c.vibephoto")
    assert db.integrity_ok() is True
    db.close()


def test_optimize_runs(tmp_path: Path) -> None:
    db = Database(tmp_path / "c.vibephoto")
    db.optimize()  # must not raise
    db.close()
