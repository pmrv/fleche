"""Tests for SQLite PRAGMA configuration in the Sql backend."""

import pytest

from fleche.storage import sql as sql_module
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


def test_wal_disabled_on_network_filesystem(tmp_path, monkeypatch):
    """A cache detected as living on a network filesystem must fall back to
    the rollback journal instead of WAL, since WAL does not work once
    writers are on different hosts (https://www.sqlite.org/wal.html).
    """
    monkeypatch.setattr(sql_module, "_is_network_filesystem", lambda path: True)
    db_path = tmp_path / "calls.db"
    sql = Sql(url=str(db_path))
    assert _journal_mode(sql) == "delete"


def test_wal_kept_when_not_network_filesystem(tmp_path, monkeypatch):
    """Sanity check that the detection hook is actually consulted and, when
    it says "local", WAL stays on.
    """
    monkeypatch.setattr(sql_module, "_is_network_filesystem", lambda path: False)
    db_path = tmp_path / "calls.db"
    sql = Sql(url=str(db_path))
    assert _journal_mode(sql) == "wal"


def test_is_network_filesystem_non_linux(monkeypatch):
    """The detector is Linux-only; other platforms conservatively report
    "not a network filesystem" rather than guessing.
    """
    monkeypatch.setattr(sql_module.sys, "platform", "darwin")
    assert sql_module._is_network_filesystem(sql_module.Path("/tmp")) is False


def test_is_network_filesystem_reads_proc_mounts(tmp_path, monkeypatch):
    """The detector matches the longest mount-point prefix against a table of
    known network filesystem types parsed from ``/proc/mounts``.
    """
    fake_mounts = tmp_path / "mounts"
    nested = tmp_path / "mnt" / "nfsshare"
    nested.mkdir(parents=True)
    fake_mounts.write_text(
        "\n".join(
            [
                "sysfs /sys sysfs rw 0 0",
                f"server:/export {tmp_path / 'mnt' / 'nfsshare'} nfs4 rw 0 0",
                "/dev/sda1 / ext4 rw 0 0",
            ]
        )
        + "\n"
    )

    real_open = open

    def fake_open(path, *args, **kwargs):
        if path == "/proc/mounts":
            return real_open(fake_mounts, *args, **kwargs)
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(sql_module, "open", fake_open, raising=False)
    monkeypatch.setattr(sql_module.sys, "platform", "linux")

    assert sql_module._is_network_filesystem(nested / "calls.db") is True
    assert sql_module._is_network_filesystem(tmp_path / "calls.db") is False
