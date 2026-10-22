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


def _start(backend, datadir, port=None, *extra, **popen):
    cmd = [sys.executable, "-m", "fleche", "db", backend, str(datadir), *extra]
    if port is not None:
        cmd += ["--port", str(port)]
    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, **popen
    )
    # The config line it prints on stdout means the server is ready.
    line = []
    reader = threading.Thread(target=lambda: line.append(proc.stdout.readline()))
    reader.start()
    reader.join(timeout=120)
    if not line or not line[0]:
        proc.kill()
        pytest.fail(f"{backend} server never got ready (exit code {proc.poll()})")
    assert line[0].startswith(f'calls = {{ type = "{backend}", datadir = ')
    assert "fleche:" not in line[0], "the password must not be printed"
    return proc, (datadir / "fleche.url").read_text().strip()


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


def test_db_server_restart_keeps_credentials_and_port(backend, tmp_path):
    datadir = tmp_path / "data"
    proc, url = _start(backend, datadir)
    assert _stop(proc) == 0
    proc, restarted = _start(backend, datadir)
    assert _stop(proc) == 0
    assert restarted == url
    port = _free_port()
    proc, moved = _start(backend, datadir, port)
    assert _stop(proc) == 0
    assert moved == url.rsplit(":", 1)[0] + f":{port}/fleche"


def test_db_server_writes_cache_table(backend, tmp_path):
    """``--cache`` without a config adds a table whose values come from the
    active (here: XDG default) cache, and that table works."""
    pytest.importorskip(DRIVERS[backend])
    pytest.importorskip("tomlkit")
    xdg = tmp_path / "xdg" / "fleche"
    xdg.mkdir(parents=True)
    (xdg / "cache.toml").write_text(
        '[default]\ncache = "persistent"\n'
        f'[persistent]\nvalues.type = "pickle"\nvalues.root = "{tmp_path / "values"}"\n'
        'calls.type = "memory"\n'
    )
    project = tmp_path / "project"
    project.mkdir()
    env = dict(os.environ, HOME=str(tmp_path), XDG_CONFIG_HOME=str(tmp_path / "xdg"))
    proc, url = _start(backend, tmp_path / "db", None, "--cache", "shared", cwd=project, env=env)
    try:
        table = fleche.config._load_config(project / "fleche.toml")["shared"]
        assert table["values"]["root"] == str(tmp_path / "values")
        assert table["calls"]["url"] == url
        cache = Cache.from_config(table)

        @fleche.fleche()
        def double(x):
            return 2 * x

        with fleche.cache(cache):
            assert double(21) == 42
        assert len(list(cache.query())) == 1
    finally:
        assert _stop(proc) == 0


def _named_square_sum(cfgdir, start):
    os.chdir(cfgdir)

    @fleche.fleche()
    def square(x):
        return x * x

    with fleche.cache("shared"):
        return sum(square(x) for x in range(start, start + 10))


def test_autostart_from_config(backend, tmp_path):
    """Cold workers race to autostart one background server from fleche.toml
    for a datadir created beforehand; the URL lands in the file, and
    ``db stop`` shuts the server down."""
    pytest.importorskip(DRIVERS[backend])
    pytest.importorskip("tomlkit")
    cfg = tmp_path / "fleche.toml"
    cfg.write_text(
        "[default]\n"
        "root = true\n\n"
        "[shared]  # cache shared by the workers\n"
        'values.type = "pickle"\n'
        'values.root = "values"\n'
        f'calls.type = "{backend}"\n'
        'calls.datadir = "db"\n'
        "calls.autostart = true\n"
    )
    datadir = tmp_path / "db"
    # Autostart never creates the database, so do that once up front.
    assert _stop(_start(backend, datadir)[0]) == 0
    try:
        with ProcessPoolExecutor(8) as pool:
            total = sum(pool.map(_named_square_sum, [tmp_path] * 16, range(0, 160, 10)))
        assert total == sum(x * x for x in range(160))

        url = (datadir / "fleche.url").read_text().strip()
        text = cfg.read_text()
        assert f'calls.url = "{url}"' in text
        assert "# cache shared by the workers" in text
        assert (datadir / "fleche.server").exists()
    finally:
        rc = subprocess.run(
            [sys.executable, "-m", "fleche", "db", "stop", str(datadir)], timeout=90
        ).returncode
    assert rc == 0
    assert not (datadir / "fleche.server").exists()
    with pytest.raises(OSError):
        socket.create_connection(("127.0.0.1", int(url.rsplit(":", 1)[1].split("/")[0])), timeout=1)
