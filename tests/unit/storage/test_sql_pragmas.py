"""Tests for SQLite PRAGMA configuration in the Sql backend."""

import pytest

from fleche.storage.sql import Sql


def _journal_mode(sql: Sql) -> str:
    with sql._session_context():
        result = sql._local.session.execute(
            __import__("sqlalchemy").text("PRAGMA journal_mode")
        )
        return result.scalar()


def test_wal_mode_on_file_backed_sqlite(tmp_path):
    """File-backed SQLite must use WAL journal mode for reduced fsync latency."""
    db_path = tmp_path / "calls.db"
    sql = Sql(url=str(db_path))
    assert _journal_mode(sql) == "wal"


def test_no_wal_mode_on_memory_sqlite():
    """In-memory SQLite must remain in the default memory journal mode."""
    sql = Sql(url=None)
    assert _journal_mode(sql) == "memory"
