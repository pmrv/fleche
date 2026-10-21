"""Host a local PostgreSQL or MariaDB server for the ``sql`` calls backend.

Two ways in, sharing one data directory layout:

* ``python -m fleche db {postgres,mariadb} DATADIR`` runs the server in the
  foreground until interrupted; ``python -m fleche db stop DATADIR`` stops a
  server started either way.
* A ``postgres`` / ``mariadb`` calls storage in ``fleche.toml`` (built by
  :func:`resolve_url`) connects to the server for ``datadir`` and, with
  ``autostart = true``, launches that same command detached when nothing is
  listening.

Either gives many processes a shared call store without sqlite's
file-locking contention.

The server binaries are not bundled: they are looked up in ``--bindir`` if
given, else on ``PATH`` and in the Debian/Ubuntu locations
(``/usr/lib/postgresql/*/bin``, ``/usr/sbin``).  A conda env with
``postgresql`` / ``mariadb`` from conda-forge works too.

On initialization a database and user, both named ``fleche``, are created
with a random password and a free port.  The full URL, password included, is
kept in ``DATADIR/fleche.url`` (mode ``0600``) and rewritten on every start
with the current host and port.  Storage built from a config file also
writes that URL back into the file as ``url`` (via ``tomlkit``, keeping
comments), so clients that cannot read ``DATADIR`` still find the server.
While a server runs, ``DATADIR/fleche.server`` records the host and pid of
the supervising ``python -m fleche db`` process.
"""

import contextvars
import glob
import json
import logging
import os
import re
import secrets
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.parse
from pathlib import Path

from filelock import FileLock

logger = logging.getLogger("fleche.dbserver")

NAME = "fleche"
URL_FILE = "fleche.url"
SERVER_FILE = "fleche.server"
BACKENDS = ("postgres", "mariadb")

# The fleche.toml whose table is being built, set by
# :func:`fleche.config.load_cache_config` so :func:`resolve_url` knows which
# file to write the URL back into.
config_file: contextvars.ContextVar[Path | None] = contextvars.ContextVar(
    "fleche_dbserver_config_file", default=None
)

# Detached servers we launched; kept referenced so their Popen objects are
# never collected (and warn) while the server outlives our interest in it.
_spawned: list[subprocess.Popen] = []


class DbServerError(RuntimeError):
    pass


def _search_path() -> str:
    """``PATH`` plus where Debian/Ubuntu packages keep the server binaries."""
    pg = sorted(
        glob.glob("/usr/lib/postgresql/*/bin"),
        key=lambda p: [int(n) for n in re.findall(r"\d+", p)],
        reverse=True,
    )
    return os.pathsep.join([os.environ.get("PATH", ""), *pg, "/usr/sbin"])


def _which(names: list[str], bindir: str | None) -> str:
    for name in names:
        found = shutil.which(name, path=bindir or _search_path())
        if found:
            return found
    where = f"in {bindir}" if bindir else "on PATH (pass --bindir to point elsewhere)"
    raise DbServerError(f"none of {', '.join(names)} found {where}")


def _run(cmd: list[str], stdin: str | None = None) -> None:
    proc = subprocess.run(cmd, input=stdin, capture_output=True, text=True)
    if proc.returncode != 0:
        raise DbServerError(
            f"{Path(cmd[0]).name} failed with exit code {proc.returncode}:\n"
            f"{proc.stdout}{proc.stderr}"
        )


def _is_initialized(backend: str, datadir: Path) -> bool:
    marker = "PG_VERSION" if backend == "postgres" else "mysql"
    return (datadir / marker).exists()


def _init_postgres(datadir: Path, password: str, bindir: str | None) -> None:
    with tempfile.NamedTemporaryFile("w", suffix=".pw") as pwfile:
        pwfile.write(password)
        pwfile.flush()
        _run([
            _which(["initdb"], bindir), "-D", str(datadir), "-U", NAME,
            "--auth=scram-sha-256", f"--pwfile={pwfile.name}", "-E", "UTF8",
        ])
    # initdb only admits loopback clients; allow password logins from anywhere
    # so ``--host 0.0.0.0`` works.  What is reachable is still decided by
    # ``listen_addresses``, i.e. ``--host``.
    with open(datadir / "pg_hba.conf", "a") as hba:
        hba.write("host all all 0.0.0.0/0 scram-sha-256\n")
        hba.write("host all all ::/0 scram-sha-256\n")
    _run(
        [_which(["postgres"], bindir), "--single", "-D", str(datadir), "postgres"],
        stdin=f"CREATE DATABASE {NAME};\n",
    )


def _init_mariadb(datadir: Path, password: str, bindir: str | None) -> None:
    _run([
        _which(["mariadb-install-db", "mysql_install_db"], bindir), "--no-defaults",
        f"--datadir={datadir}", "--auth-root-authentication-method=socket",
        "--skip-test-db",
    ])
    # Grant tables are not loaded in bootstrap mode until FLUSH PRIVILEGES.
    _run(
        [_which(["mariadbd", "mysqld"], bindir), "--no-defaults",
         f"--datadir={datadir}", "--bootstrap"],
        stdin=(
            "FLUSH PRIVILEGES;\n"
            f"CREATE DATABASE {NAME};\n"
            f"CREATE USER '{NAME}'@'%' IDENTIFIED BY '{password}';\n"
            f"GRANT ALL ON {NAME}.* TO '{NAME}'@'%';\n"
        ),
    )


def _server_command(
    backend: str, datadir: Path, host: str, port: int, bindir: str | None, sockdir: str
) -> list[str]:
    if backend == "postgres":
        return [
            _which(["postgres"], bindir), "-D", str(datadir), "-p", str(port),
            "-c", f"listen_addresses={host}", "-c", "unix_socket_directories=",
        ]
    # mariadbd always opens a unix socket; datadir paths can exceed the ~107
    # byte sun_path limit, so put it in a short temporary directory.
    return [
        _which(["mariadbd", "mysqld"], bindir), "--no-defaults",
        f"--datadir={datadir}", f"--bind-address={host}", f"--port={port}",
        f"--socket={sockdir}/mariadb.sock",
    ]


def make_url(backend: str, password: str, host: str, port: int) -> str:
    if host in ("0.0.0.0", "::", "*"):
        host = socket.getfqdn()
    if ":" in host:
        host = f"[{host}]"
    scheme = "postgresql+psycopg2" if backend == "postgres" else "mysql+pymysql"
    return f"{scheme}://{NAME}:{password}@{host}:{port}/{NAME}"


def _probe_address(host: str) -> str:
    return {"0.0.0.0": "127.0.0.1", "*": "127.0.0.1", "::": "::1"}.get(host, host)


def _port_open(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.5):
            return True
    except OSError:
        return False


def _wait_for_port(proc: subprocess.Popen, host: str, port: int, timeout: float) -> None:
    probe = _probe_address(host)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise DbServerError(f"server exited during startup with code {proc.returncode}")
        if _port_open(probe, port):
            return
        time.sleep(0.2)
    raise DbServerError(f"server did not open {probe}:{port} within {timeout:g}s")


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _write_private(path: Path, text: str) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(text)


def _sidecar(datadir: Path, suffix: str) -> Path:
    """A file next to *datadir*; inside it would break ``initdb``'s
    empty-directory requirement."""
    return datadir.with_name(datadir.name + suffix)


def _read_url(datadir: Path) -> str | None:
    try:
        return (datadir / URL_FILE).read_text().strip() or None
    except OSError:
        return None


def _url_reachable(url: str) -> bool:
    parts = urllib.parse.urlsplit(url)
    return bool(parts.hostname and parts.port) and _port_open(parts.hostname, parts.port)


def _read_server_info(datadir: Path) -> dict | None:
    try:
        return json.loads((datadir / SERVER_FILE).read_text())
    except (OSError, ValueError):
        return None


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def serve(
    backend: str,
    datadir: str | Path,
    host: str = "127.0.0.1",
    port: int | None = None,
    bindir: str | None = None,
    startup_timeout: float = 60.0,
) -> int:
    """Initialize *datadir* if needed and run the server until SIGINT/SIGTERM.

    *port* defaults to the one used last time, or a free one on first use.
    Returns the server's exit code.
    """
    if backend not in BACKENDS:
        raise DbServerError(f"unknown backend {backend!r}; expected one of {list(BACKENDS)}")
    datadir = Path(datadir).expanduser().resolve()
    url_file = datadir / URL_FILE
    server_file = datadir / SERVER_FILE

    if _is_initialized(backend, datadir):
        if not url_file.exists():
            raise DbServerError(f"{datadir} was not initialized by fleche (no {URL_FILE})")
        previous = urllib.parse.urlsplit(url_file.read_text().strip())
        password = previous.password or ""
        port = port or previous.port
    else:
        if datadir.exists() and any(datadir.iterdir()):
            raise DbServerError(f"{datadir} is not empty and not a {backend} data directory")
        datadir.mkdir(mode=0o700, parents=True, exist_ok=True)
        password = secrets.token_urlsafe(24)
        print(f"initializing {backend} data directory {datadir}", file=sys.stderr)
        init = _init_postgres if backend == "postgres" else _init_mariadb
        try:
            init(datadir, password, bindir)
        except BaseException:
            # Leave nothing half-initialized for the next run to trip over.
            shutil.rmtree(datadir, ignore_errors=True)
            raise
    port = port or _free_port()

    # Otherwise the readiness probe below would find that server instead.
    if _port_open(_probe_address(host), port):
        raise DbServerError(f"port {port} is already in use; pick another with --port")

    url = make_url(backend, password, host, port)
    _write_private(url_file, url + "\n")

    with tempfile.TemporaryDirectory(prefix="fleche-db-") as sockdir:
        cmd = _server_command(backend, datadir, host, port, bindir, sockdir)
        # Before the server opens its port, so autostarters wait for us
        # instead of launching a second server on the same datadir.
        _write_private(server_file, json.dumps(
            {"host": socket.gethostname(), "pid": os.getpid(), "port": port}
        ))
        # Own session, so a terminal ^C reaches only us and we pick the stop
        # signal: SIGINT is postgres' "fast" shutdown (SIGTERM waits for every
        # client to disconnect), mariadbd ignores SIGINT and stops on SIGTERM.
        proc = subprocess.Popen(cmd, start_new_session=True)
        stop_signal = signal.SIGINT if backend == "postgres" else signal.SIGTERM

        def _forward(signum, frame):
            if proc.poll() is None:
                proc.send_signal(stop_signal)

        previous_handlers = {
            s: signal.signal(s, _forward) for s in (signal.SIGINT, signal.SIGTERM)
        }
        try:
            _wait_for_port(proc, host, port, startup_timeout)
            print(f"# {backend} ready on {host}:{port}; use it from fleche.toml as", file=sys.stderr)
            print(
                f"calls = {{ type = \"{backend}\", datadir = {json.dumps(str(datadir))} }}",
                flush=True,
            )
            return proc.wait()
        except BaseException:
            _forward(None, None)
            proc.wait()
            raise
        finally:
            server_file.unlink(missing_ok=True)
            for s, handler in previous_handlers.items():
                signal.signal(s, handler)


def stop(datadir: str | Path, timeout: float = 60.0) -> int:
    """Stop the server running for *datadir* on this host."""
    datadir = Path(datadir).expanduser().resolve()
    info = _read_server_info(datadir)
    if info is None:
        print(f"no server running for {datadir}", file=sys.stderr)
        return 0
    if info["host"] != socket.gethostname():
        raise DbServerError(f"the server for {datadir} runs on {info['host']}; stop it there")
    try:
        os.kill(info["pid"], signal.SIGTERM)
    except ProcessLookupError:
        (datadir / SERVER_FILE).unlink(missing_ok=True)
        return 0
    # The supervisor removes SERVER_FILE once the server has exited; its pid
    # alone could linger as a zombie of whoever autostarted it.
    deadline = time.monotonic() + timeout
    while (datadir / SERVER_FILE).exists() and _pid_alive(info["pid"]):
        if time.monotonic() > deadline:
            raise DbServerError(f"server for {datadir} did not stop within {timeout:g}s")
        time.sleep(0.2)
    return 0


def _autostart(
    backend: str, datadir: Path, host: str, port: int | None, bindir: str | None, timeout: float
) -> str:
    datadir.parent.mkdir(parents=True, exist_ok=True)
    # Serializes processes racing to autostart the same server.
    with FileLock(_sidecar(datadir, ".lock")):
        url = _read_url(datadir)
        if url and _url_reachable(url):
            return url
        proc = None
        log = _sidecar(datadir, ".log")
        info = _read_server_info(datadir)
        if info is not None and info["host"] != socket.gethostname():
            raise DbServerError(
                f"the server for {datadir} is recorded as running on {info['host']} "
                f"but is unreachable from here; not starting a second one on the same "
                f"data directory (delete {datadir / SERVER_FILE} if it is dead)"
            )
        if info is None or not _pid_alive(info["pid"]):
            cmd = [sys.executable, "-m", "fleche", "db", backend, str(datadir), "--host", host]
            if port:
                cmd += ["--port", str(port)]
            if bindir:
                cmd += ["--bindir", bindir]
            logger.info("autostarting %s server for %s (log: %s)", backend, datadir, log)
            with open(log, "ab") as out:
                proc = subprocess.Popen(
                    cmd, stdin=subprocess.DEVNULL, stdout=out, stderr=out,
                    start_new_session=True,
                )
            _spawned.append(proc)
        # Else a server is already starting (pid alive, port not open yet).
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            url = _read_url(datadir)
            if url and _url_reachable(url):
                return url
            if proc is not None and proc.poll() is not None:
                raise DbServerError(
                    f"{backend} server exited with code {proc.returncode}; see {log}"
                )
            time.sleep(0.2)
    raise DbServerError(f"{backend} server for {datadir} not ready within {timeout:g}s; see {log}")


def resolve_url(
    backend: str,
    datadir: str | Path | None = None,
    url: str | None = None,
    autostart: bool = False,
    host: str = "127.0.0.1",
    port: int | None = None,
    bindir: str | None = None,
    startup_timeout: float = 120.0,
) -> str:
    """Return the SQLAlchemy URL of the server for *datadir*, starting it if
    *autostart* and nothing is listening.

    ``DATADIR/fleche.url`` wins over *url*, which only matters to clients
    that cannot read *datadir*.  When building from a config file, a missing
    or outdated *url* is written back into it.
    """
    if backend not in BACKENDS:
        raise DbServerError(f"unknown backend {backend!r}; expected one of {list(BACKENDS)}")
    if datadir is None:
        if url is None:
            raise DbServerError(f"a {backend} calls storage needs `datadir` or `url`")
        return url
    datadir = Path(datadir).expanduser().resolve()
    current = _read_url(datadir) or url
    if current is None or not _url_reachable(current):
        if not autostart:
            raise DbServerError(
                f"no {backend} server is running for {datadir}; start one with "
                f"`python -m fleche db {backend} {datadir}` or set `autostart = true`"
            )
        current = _autostart(backend, datadir, host, port, bindir, startup_timeout)
    source = config_file.get()
    if source is not None and current != url:
        store_url(source, backend, datadir, current)
    return current


def _same_dir(raw: str, base: Path, datadir: Path) -> bool:
    """Whether the config value *raw* (relative to the file's directory
    *base*, as :func:`fleche.config._rebase_config` reads it) is *datadir*."""
    path = Path(raw).expanduser()
    return (path if path.is_absolute() else base / path).resolve() == datadir


def store_url(config_path: Path, backend: str, datadir: Path, url: str) -> bool:
    """Set ``url`` on every *backend* table in *config_path* whose ``datadir``
    is *datadir*.  Returns whether the file changed.

    Best effort: a missing ``tomlkit``, an unwritable file or one that no
    longer parses only logs a warning, since the URL is also in *datadir*.
    """
    try:
        import tomlkit
    except ImportError:
        logger.warning("install tomlkit to have fleche store the %s URL in %s", backend, config_path)
        return False
    try:
        with FileLock(_sidecar(datadir, ".lock")):
            doc = tomlkit.parse(config_path.read_text())
            changed = False

            def visit(node):
                nonlocal changed
                if isinstance(node, dict):
                    if (
                        node.get("type") == backend
                        and "datadir" in node
                        and _same_dir(str(node["datadir"]), config_path.parent, datadir)
                        and node.get("url") != url
                    ):
                        node["url"] = url
                        changed = True
                    for value in node.values():
                        visit(value)
                elif isinstance(node, list):
                    for value in node:
                        visit(value)

            visit(doc)
            if changed:
                fd, tmp = tempfile.mkstemp(dir=config_path.parent, prefix=f".{config_path.name}.")
                with os.fdopen(fd, "w") as f:
                    f.write(tomlkit.dumps(doc))
                shutil.copymode(config_path, tmp)
                os.replace(tmp, config_path)
                logger.info("stored the %s URL for %s in %s", backend, datadir, config_path)
            return changed
    except Exception as e:
        logger.warning("could not store the %s URL in %s: %s", backend, config_path, e)
        return False
