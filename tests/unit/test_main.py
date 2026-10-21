"""Unit tests for the ``python -m fleche`` CLI dispatcher in :mod:`fleche.__main__`.

The integration tests in ``tests/integration/test_remote.py`` exercise the
dispatcher end-to-end via a real subprocess, but coverage of ``__main__.py``
itself does not propagate out of that subprocess.  These tests drive
``_main`` in-process so the argument parsing and branch dispatching are
recorded by the parent coverage run.
"""

import pytest

import fleche.remote
from fleche.__main__ import _main


def test_main_serve_dispatches_to_run_server_with_default_cache(monkeypatch):
    """Without ``--cache``, the dispatcher forwards ``cache_name=None`` and
    returns the server's exit code."""
    received = []
    monkeypatch.setattr(
        fleche.remote, "_run_server", lambda cache_name: received.append(cache_name) or 0
    )

    rc = _main(["remote", "--serve"])

    assert rc == 0
    assert received == [None]


def test_main_serve_forwards_named_cache(monkeypatch):
    """``--cache NAME`` is parsed and threaded through to ``_run_server``."""
    received = []
    monkeypatch.setattr(
        fleche.remote, "_run_server", lambda cache_name: received.append(cache_name) or 0
    )

    rc = _main(["remote", "--serve", "--cache", "mycache"])

    assert rc == 0
    assert received == ["mycache"]


def test_main_remote_without_serve_errors():
    """``remote`` without ``--serve`` exits with the argparse error code (2)
    rather than silently no-oping."""
    with pytest.raises(SystemExit) as excinfo:
        _main(["remote"])
    assert excinfo.value.code == 2


def test_main_missing_subcommand_errors():
    """A bare invocation with no subcommand fails parsing (required=True)."""
    with pytest.raises(SystemExit) as excinfo:
        _main([])
    assert excinfo.value.code == 2


def test_main_db_dispatches_to_serve(monkeypatch):
    import fleche.dbserver

    received = []
    monkeypatch.setattr(
        fleche.dbserver, "serve", lambda *args, **kwargs: received.append((args, kwargs)) or 0
    )

    rc = _main(["db", "mariadb", "data", "--host", "0.0.0.0", "--port", "3307"])

    assert rc == 0
    assert received == [
        (("mariadb", "data"), {"host": "0.0.0.0", "port": 3307, "bindir": None})
    ]


def test_main_db_reports_server_errors(monkeypatch, capsys):
    """A :class:`DbServerError` becomes a one-line message and exit code 1."""
    import fleche.dbserver

    def fail(*args, **kwargs):
        raise fleche.dbserver.DbServerError("no initdb found")

    monkeypatch.setattr(fleche.dbserver, "serve", fail)

    assert _main(["db", "postgres", "data"]) == 1
    assert capsys.readouterr().err == "error: no initdb found\n"


def test_main_db_rejects_unknown_backend():
    with pytest.raises(SystemExit) as excinfo:
        _main(["db", "sqlite", "data"])
    assert excinfo.value.code == 2


def test_main_db_stop_dispatches_to_stop(monkeypatch):
    import fleche.dbserver

    received = []
    monkeypatch.setattr(fleche.dbserver, "stop", lambda datadir: received.append(datadir) or 0)

    assert _main(["db", "stop", "data"]) == 0
    assert received == ["data"]
