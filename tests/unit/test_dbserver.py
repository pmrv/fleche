"""Unit tests for :mod:`fleche.dbserver` that need no database binaries.

Booting real servers is covered in ``tests/integration/test_dbserver.py``.
"""

import socket

import pytest

from fleche.dbserver import DbServerError, make_url, serve


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
