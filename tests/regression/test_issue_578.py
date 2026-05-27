"""Regression test for issue #578: integer version column in legacy SQLite databases.

Before #396 the `version` column was stored as a raw INTEGER.  After #396 it is
JSON-encoded TEXT.  Opening an old DB with the new code must not crash when the
column retains its INTEGER affinity and SQLite returns Python int values.
"""

import sqlite3

import pytest

pytest.importorskip("sqlalchemy")

from fleche.storage.sql import Sql


def _make_legacy_db(path):
    """Create a minimal SQLite database that mimics the pre-#396 schema.

    The `version` column is declared INTEGER (old schema) and a row is inserted
    with an integer version value so that SQLite returns an int on read,
    triggering the backwards-compat crash.
    """
    con = sqlite3.connect(str(path))
    con.executescript(
        """
        CREATE TABLE calls (
            key       TEXT PRIMARY KEY,
            name      TEXT NOT NULL,
            module    TEXT,
            version   INTEGER,
            code_digest TEXT,
            result    TEXT
        );
        CREATE TABLE arguments (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            call_key  TEXT NOT NULL REFERENCES calls(key) ON DELETE CASCADE,
            position  INTEGER NOT NULL,
            name      TEXT NOT NULL,
            value     TEXT NOT NULL,
            UNIQUE(call_key, name)
        );
        CREATE TABLE metadata (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            call_key  TEXT NOT NULL REFERENCES calls(key) ON DELETE CASCADE,
            name      TEXT NOT NULL,
            data      TEXT,
            UNIQUE(call_key, name)
        );
        INSERT INTO calls (key, name, module, version, code_digest, result)
        VALUES (
            'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
            'my_func',
            'my_module',
            1,
            NULL,
            NULL
        );
        """
    )
    con.close()


def test_load_from_legacy_integer_version_db(tmp_path):
    """Loading a call whose version is stored as a raw INTEGER must not raise TypeError."""
    db_path = tmp_path / "legacy.db"
    _make_legacy_db(db_path)

    sql = Sql(str(db_path))
    from fleche.digest import Digest

    key = Digest("a" * 64)
    call = sql.load(key)
    assert call.version == 1
