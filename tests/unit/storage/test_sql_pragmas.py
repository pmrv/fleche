"""Tests for SQLite PRAGMA configuration in the Sql backend."""

import pytest
# Named imports rather than attribute access off the package: sqlalchemy's
# ``__init__`` does not re-export the ``event`` submodule, so ``sqlalchemy.event``
# resolves only when something else has already imported it.  No importorskip is
# needed — ``tests/fixtures.py``, registered as a conftest plugin, imports
# sqlalchemy unconditionally.
from sqlalchemy import create_engine, create_mock_engine, event, text

from fleche.storage import sql as sql_module
from fleche.storage.sql import Sql


def _journal_mode(sql: Sql) -> str:
    with sql._session_context():
        result = sql._local.session.execute(text("PRAGMA journal_mode"))
        return result.scalar()


def _record_statements(engine) -> list[str]:
    """Collect every SQL statement executed against ``engine`` into a list."""
    statements: list[str] = []
    event.listen(
        engine,
        "before_cursor_execute",
        lambda conn, cursor, statement, *args: statements.append(statement),
    )
    return statements


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


def test_is_network_filesystem_duplicate_mount_point_last_wins(tmp_path, monkeypatch):
    """``/proc/mounts`` can list the same mount point twice, e.g. an autofs
    trigger followed by the real NFS mount it resolves to. The later entry
    must win the tie so the detector reports the actual (network) fstype
    instead of the autofs placeholder (see #821).
    """
    fake_mounts = tmp_path / "mounts"
    home = tmp_path / "home"
    home.mkdir()
    fake_mounts.write_text(
        "\n".join(
            [
                "/dev/sda1 / ext4 rw 0 0",
                f"/etc/auto.home {home} autofs rw,fd=57 0 0",
                f"server:/export {home} nfs rw,vers=3 0 0",
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

    assert sql_module._is_network_filesystem(home / "calls.db") is True


def test_is_network_filesystem_skips_malformed_mount_lines(tmp_path, monkeypatch):
    """A ``/proc/mounts`` line with fewer than three fields is skipped rather
    than raising ``IndexError``, so one odd line cannot stop the detector from
    seeing the network mount further down the table.
    """
    fake_mounts = tmp_path / "mounts"
    share = tmp_path / "share"
    share.mkdir()
    fake_mounts.write_text(
        "\n".join(
            [
                "/dev/sda1 / ext4 rw 0 0",
                "truncated line",
                f"server:/export {share} cifs rw 0 0",
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

    assert sql_module._is_network_filesystem(share / "calls.db") is True


def test_is_network_filesystem_reports_local_when_proc_mounts_is_unreadable(monkeypatch):
    """The docstring promises that *any* failure to determine the filesystem
    type degrades to "not a network filesystem" — a container or hardened
    kernel that denies ``/proc/mounts`` must not block database creation.
    """

    def exploding_open(path, *args, **kwargs):
        raise OSError("permission denied")

    monkeypatch.setattr(sql_module, "open", exploding_open, raising=False)
    monkeypatch.setattr(sql_module.sys, "platform", "linux")

    assert sql_module._is_network_filesystem(sql_module.Path("/tmp/calls.db")) is False


def test_configure_pragmas_is_a_no_op_for_non_sqlite_dialects():
    """PRAGMA is sqlite-only, so the configurator must bail out on the dialect
    name *before* registering its ``connect`` listener — the Postgres/MySQL
    parametrizations of the ``call_storage`` fixture depend on it.

    A mock engine stands in for the real thing: it carries a dialect but
    supports no event registration, so an unguarded configurator raises here.
    """
    engine = create_mock_engine("postgresql://", lambda *a, **kw: None)

    sql_module._configure_sqlite_pragmas(engine, None)


def test_memory_sqlite_skips_the_journal_mode_round_trip():
    """``journal_mode`` is persisted in the database *file*, so setting it on an
    in-memory database is a silent no-op that costs one extra connection.  The
    ``is_memory`` short-circuit must actually fire — it reads the parsed URL
    because ``str(engine.url)`` percent-encodes the colons in ``:memory:``.
    """
    memory = create_engine("sqlite:///:memory:", future=True)
    memory_statements = _record_statements(memory)
    sql_module._configure_sqlite_pragmas(memory, None)

    assert not any("journal_mode" in s for s in memory_statements)


def test_file_backed_sqlite_still_takes_the_journal_mode_round_trip(tmp_path):
    """Control for the in-memory skip above: the short-circuit must not widen
    to file-backed databases, which are the ones WAL is for.
    """
    db_path = tmp_path / "calls.db"
    on_disk = create_engine(f"sqlite:///{db_path}", future=True)
    on_disk_statements = _record_statements(on_disk)
    sql_module._configure_sqlite_pragmas(on_disk, db_path)

    assert any("journal_mode" in s for s in on_disk_statements)
