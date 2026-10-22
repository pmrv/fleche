"""Unit tests for :mod:`fleche.dbserver` that need no database binaries.

Booting real servers is covered in ``tests/integration/test_dbserver.py``.
"""

import json
import socket

import pytest

from fleche import config as fleche_config
from fleche.dbserver import DbServerError, make_url, resolve_url, serve, stop


@pytest.mark.parametrize(
    "backend, host, expected",
    [
        ("postgres", "127.0.0.1", "postgresql+psycopg2://fleche:pw@127.0.0.1:5432/fleche"),
        ("mariadb", "db.example", "mysql+pymysql://fleche:pw@db.example:5432/fleche"),
        ("postgres", "::1", "postgresql+psycopg2://fleche:pw@[::1]:5432/fleche"),
    ],
)
def test_make_url(backend, host, expected):
    assert make_url(backend, "pw", host, 5432) == expected


def test_make_url_wildcard_host_uses_fqdn():
    """Listening on all interfaces advertises a name other nodes can reach."""
    assert make_url("postgres", "pw", "0.0.0.0", 1) == (
        f"postgresql+psycopg2://fleche:pw@{socket.getfqdn()}:1/fleche"
    )


def test_serve_rejects_unknown_backend(tmp_path):
    with pytest.raises(DbServerError, match="unknown backend"):
        serve("sqlite", tmp_path)


def test_serve_refuses_non_empty_foreign_datadir(tmp_path):
    (tmp_path / "precious.txt").write_text("keep me")
    with pytest.raises(DbServerError, match="not empty"):
        serve("postgres", tmp_path)
    assert (tmp_path / "precious.txt").read_text() == "keep me"


def test_serve_refuses_datadir_not_initialized_by_fleche(tmp_path):
    (tmp_path / "PG_VERSION").write_text("16\n")
    with pytest.raises(DbServerError, match="not initialized by fleche"):
        serve("postgres", tmp_path)


def test_serve_reports_missing_binaries(tmp_path):
    with pytest.raises(DbServerError, match="initdb"):
        serve("postgres", tmp_path / "data", bindir=str(tmp_path))


def test_serve_refuses_port_in_use(tmp_path):
    """Another server on the port would fool the readiness probe."""
    datadir = tmp_path / "data"
    datadir.mkdir()
    (datadir / "PG_VERSION").write_text("16\n")
    (datadir / "fleche.url").write_text("postgresql+psycopg2://fleche:pw@127.0.0.1:1/fleche\n")
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        port = listener.getsockname()[1]
        with pytest.raises(DbServerError, match="already in use"):
            serve("postgres", datadir, port=port)


# --- resolve_url / stop without server binaries ---------------------------


@pytest.fixture
def listener():
    """A socket accepting connections, standing in for a running server."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        s.listen()
        yield s.getsockname()[1]


def _fake_datadir(path, port, password="pw"):
    path.mkdir()
    (path / "PG_VERSION").write_text("16\n")
    url = f"postgresql+psycopg2://fleche:{password}@127.0.0.1:{port}/fleche"
    (path / "fleche.url").write_text(url + "\n")
    return url


def test_resolve_url_without_server_or_autostart_says_how_to_start_one(tmp_path):
    with pytest.raises(DbServerError, match="python -m fleche db postgres .*autostart = true"):
        resolve_url("postgres", tmp_path / "db")


def test_resolve_url_needs_datadir_or_url():
    assert resolve_url("mariadb", url="mysql+pymysql://a:b@h:1/fleche") == "mysql+pymysql://a:b@h:1/fleche"
    with pytest.raises(DbServerError, match="needs `datadir` or `url`"):
        resolve_url("mariadb")


def test_resolve_url_prefers_the_datadir_url(tmp_path, listener):
    url = _fake_datadir(tmp_path / "db", listener)
    stale = "postgresql+psycopg2://fleche:old@127.0.0.1:1/fleche"
    assert resolve_url("postgres", tmp_path / "db", url=stale) == url


def test_resolve_url_falls_back_to_config_url(tmp_path, listener):
    """Clients that cannot read the datadir (another node) use the stored url."""
    url = f"postgresql+psycopg2://fleche:pw@127.0.0.1:{listener}/fleche"
    assert resolve_url("postgres", tmp_path / "elsewhere", url=url) == url


@pytest.mark.parametrize("make", ["missing", "empty", "no-url"])
def test_autostart_never_creates_a_database(tmp_path, make):
    datadir = tmp_path / "db"
    if make != "missing":
        datadir.mkdir()
    if make == "no-url":
        (datadir / "PG_VERSION").write_text("16\n")
    with pytest.raises(DbServerError, match="create it once with `python -m fleche db postgres"):
        resolve_url("postgres", datadir, autostart=True)
    assert not (datadir / "fleche.url").exists()


def test_autostart_refuses_datadir_served_from_another_host(tmp_path):
    datadir = tmp_path / "db"
    _fake_datadir(datadir, 1)
    (datadir / "fleche.server").write_text(json.dumps({"host": "elsewhere", "pid": 1, "port": 1}))
    with pytest.raises(DbServerError, match="running on elsewhere"):
        resolve_url("postgres", datadir, autostart=True)


def test_stop_without_server_is_a_noop(tmp_path):
    assert stop(tmp_path) == 0


def test_stop_refuses_server_on_another_host(tmp_path):
    (tmp_path / "fleche.server").write_text(json.dumps({"host": "elsewhere", "pid": 1, "port": 1}))
    with pytest.raises(DbServerError, match="runs on elsewhere"):
        stop(tmp_path)


def test_stop_clears_record_of_dead_server(tmp_path):
    (tmp_path / "fleche.server").write_text(
        json.dumps({"host": socket.gethostname(), "pid": 2**22 + 12345, "port": 1})
    )
    assert stop(tmp_path) == 0
    assert not (tmp_path / "fleche.server").exists()


def test_config_rebases_datadir(tmp_path, monkeypatch):
    """A relative ``datadir`` means relative to its fleche.toml."""
    (tmp_path / "sub").mkdir()
    (tmp_path / "fleche.toml").write_text(
        '[default]\nroot = true\n[c]\ncalls.type = "postgres"\ncalls.datadir = "db"\n'
    )
    (tmp_path / "sub" / "fleche.toml").write_text('[d]\ncalls.type = "memory"\n')
    monkeypatch.chdir(tmp_path / "sub")
    merged = fleche_config._load_merged_config()
    assert merged["c"]["calls"]["datadir"] == str(tmp_path / "db")
