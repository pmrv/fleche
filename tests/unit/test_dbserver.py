"""Unit tests for :mod:`fleche.dbserver` that need no database binaries.

Booting real servers is covered in ``tests/integration/test_dbserver.py``.
"""

import json
import socket

import pytest

from fleche import config as fleche_config
from fleche import dbserver
from fleche.dbserver import DbServerError, make_url, resolve_url, serve, stop, store_url


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


# --- resolve_url / store_url / stop without server binaries -----------------


@pytest.fixture
def listener():
    """A socket accepting connections, standing in for a running server."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        s.listen()
        yield s.getsockname()[1]


def _fake_datadir(path, port, password="pw"):
    path.mkdir()
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


def test_resolve_url_writes_url_back_into_declaring_file(tmp_path, listener):
    url = _fake_datadir(tmp_path / "db", listener)
    cfg = tmp_path / "fleche.toml"
    cfg.write_text('[c]\ncalls.type = "postgres"\ncalls.datadir = "db"\n')
    token = dbserver.config_file.set(cfg)
    try:
        resolve_url("postgres", tmp_path / "db")
    finally:
        dbserver.config_file.reset(token)
    assert f'calls.url = "{url}"' in cfg.read_text()


CONFIG = """\
# keep this comment
[default]
root = true

[dotted]
values.type = "memory"
calls.type = "postgres"  # and this one
calls.datadir = "db"

[inline]
values = {type = "memory"}
calls = {type = "postgres", datadir = "db"}

[[stack]]
values.type = "memory"
calls.type = "memory"

[[stack]]
values.type = "memory"
[stack.calls]
type = "postgres"
datadir = "DATADIR"

[other]
values.type = "memory"
calls.type = "postgres"
calls.datadir = "elsewhere"

[wrong_backend]
values.type = "memory"
calls.type = "mariadb"
calls.datadir = "db"
"""


def test_store_url_updates_every_matching_table_in_place(tmp_path):
    cfg = tmp_path / "fleche.toml"
    cfg.write_text(CONFIG.replace("DATADIR", str(tmp_path / "db")))
    cfg.chmod(0o640)
    url = "postgresql+psycopg2://fleche:pw@h:1/fleche"

    assert store_url(cfg, "postgres", tmp_path / "db", url)

    text = cfg.read_text()
    assert "# keep this comment" in text and "# and this one" in text
    parsed = fleche_config._load_config(cfg)
    assert parsed["dotted"]["calls"]["url"] == url
    assert parsed["inline"]["calls"]["url"] == url
    assert parsed["stack"][1]["calls"]["url"] == url
    assert "url" not in parsed["other"]["calls"]
    assert "url" not in parsed["wrong_backend"]["calls"]
    assert cfg.stat().st_mode & 0o777 == 0o640
    # A second writer racing the first finds nothing left to do.
    assert not store_url(cfg, "postgres", tmp_path / "db", url)


def test_store_url_never_raises(tmp_path):
    """The URL is also in the datadir, so a broken config only warns."""
    cfg = tmp_path / "fleche.toml"
    cfg.write_text("not = [valid toml")
    assert not store_url(cfg, "postgres", tmp_path / "db", "postgresql+psycopg2://x")


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


def test_config_rebases_datadir_and_records_sources(tmp_path, monkeypatch):
    """A relative ``datadir`` means relative to its fleche.toml, and the
    loader remembers that file for the write-back."""
    (tmp_path / "sub").mkdir()
    (tmp_path / "fleche.toml").write_text(
        '[default]\nroot = true\n[c]\ncalls.type = "postgres"\ncalls.datadir = "db"\n'
    )
    (tmp_path / "sub" / "fleche.toml").write_text('[d]\ncalls.type = "memory"\n')
    monkeypatch.chdir(tmp_path / "sub")
    merged, sources = fleche_config._load_merged_config_with_sources()
    assert merged["c"]["calls"]["datadir"] == str(tmp_path / "db")
    assert sources == {
        "default": tmp_path / "fleche.toml",
        "c": tmp_path / "fleche.toml",
        "d": tmp_path / "sub" / "fleche.toml",
    }
