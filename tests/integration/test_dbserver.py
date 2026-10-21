"""Boot real PostgreSQL / MariaDB servers via ``python -m fleche db``.

Skipped unless the server binaries are installed (see
:func:`fleche.dbserver._which` for where they are looked up) and we are not
root (postgres refuses to run as root).  The parallel round-trip additionally
needs the client driver the printed URL names.
"""

import os
import signal
import socket
import subprocess
import sys
import threading
from concurrent.futures import ProcessPoolExecutor

import pytest

import fleche
from fleche.caches import Cache
from fleche.dbserver import DbServerError, _which

BINARIES = {
    "postgres": [["initdb"], ["postgres"]],
    "mariadb": [["mariadb-install-db", "mysql_install_db"], ["mariadbd", "mysqld"]],
}
DRIVERS = {"postgres": "psycopg2", "mariadb": "pymysql"}


def _have(backend):
    try:
        for names in BINARIES[backend]:
            _which(names, None)
    except DbServerError:
        return False
    return True


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _start(backend, datadir, port):
    proc = subprocess.Popen(
        [sys.executable, "-m", "fleche", "db", backend, str(datadir), "--port", str(port)],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    line = []
    reader = threading.Thread(target=lambda: line.append(proc.stdout.readline()))
    reader.start()
    reader.join(timeout=120)
    if not line or not line[0]:
        proc.kill()
        pytest.fail(f"{backend} server printed no URL (exit code {proc.poll()})")
    return proc, line[0].strip()


def _stop(proc):
    proc.send_signal(signal.SIGINT)
    return proc.wait(timeout=60)


def _square_sum(cfg, start):
    @fleche.fleche()
    def square(x):
        return x * x

    with fleche.cache(Cache.from_config(cfg)):
        return sum(square(x) for x in range(start, start + 10))


@pytest.fixture(params=["postgres", "mariadb"])
def backend(request):
    if os.geteuid() == 0:
        pytest.skip("database servers refuse to run as root")
    if not _have(request.param):
        pytest.skip(f"{request.param} server binaries not installed")
    return request.param


def test_db_server_serves_parallel_writers(backend, tmp_path):
    pytest.importorskip(DRIVERS[backend])
    datadir = tmp_path / "data"
    proc, url = _start(backend, datadir, _free_port())
    try:
        assert (datadir / "fleche.url").read_text().strip() == url
        assert (datadir / "fleche.url").stat().st_mode & 0o777 == 0o600
        # Fresh database plus concurrent first writers: the schema-creation
        # and InnoDB deadlock races in Sql both show up here.
        cfg = {
            "values": {"type": "pickle", "root": str(tmp_path / "values")},
            "calls": {"type": "sql", "url": url},
        }
        with ProcessPoolExecutor(8) as pool:
            total = sum(pool.map(_square_sum, [cfg] * 16, range(0, 160, 10)))
        assert total == sum(x * x for x in range(160))
        assert len(list(Cache.from_config(cfg).query())) == 160
    finally:
        assert _stop(proc) == 0


def test_db_server_restart_keeps_credentials(backend, tmp_path):
    datadir = tmp_path / "data"
    proc, url = _start(backend, datadir, _free_port())
    assert _stop(proc) == 0
    port = _free_port()
    proc, restarted = _start(backend, datadir, port)
    assert _stop(proc) == 0
    assert restarted == url.rsplit(":", 1)[0] + f":{port}/fleche"
