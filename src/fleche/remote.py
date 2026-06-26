"""SSH-connected cache for sharing fleche results across machines.

:class:`SshCache` is a :class:`~fleche.caches.BaseCache` that forwards every
operation to a remote ``python -m fleche remote --serve`` process over a
single persistent SSH subprocess.  The remote process loads its own
``fleche.toml`` and proxies operations into whichever cache it has
configured, so the remote side keeps full freedom to use any backend
(file / SQL / HDF5 / stack).

Typical configuration in ``fleche.toml`` — local cache first, remote cache
second, composed automatically into a :class:`~fleche.caches.CacheStack`::

    [default]
    cache = "shared"

    [[shared]]                          # local layer (saves go here)
    values.type = "cloudpickle"
    values.root = "~/.fleche/values"
    calls.type = "sql"
    calls.url = "sqlite:///~/.fleche/calls.db"

    [[shared]]                          # remote layer (read-through)
    type = "ssh"
    host = "marvin@bigpc.example.com"
    cache_name = "shared"               # optional: named cache on remote
    python = "python3"                  # optional
    ssh_options = ["-o", "ControlMaster=auto",
                   "-o", "ControlPath=~/.ssh/cm-%r@%h:%p",
                   "-o", "ControlPersist=10m"]
    setup_commands = ["module load python/3.11",
                      "source ~/.venv/bin/activate"]    # optional
    workdir = "~/project"               # optional: cd before launching server

ControlMaster + ControlPersist in ``~/.ssh/config`` (or via ``ssh_options``)
mean 2FA is prompted once and then re-used across multiple fleche sessions
within the persist window.  The SSH subprocess is spawned lazily on the first
cache operation and reused for the lifetime of the Python process, so within
a single run only one authentication round-trip is required.
"""

import abc
import atexit
import collections
import logging
import os
import shlex
import socket
import struct
import subprocess
import sys
import threading
import traceback
from dataclasses import dataclass, field
from typing import Any, Iterable

from pyiron_snippets.import_alarm import ImportAlarm

from . import call as _call
from .caches import BaseCache, Rejected
from .call import Call, DigestedCall, LazyCall, QueryCall
from .digest import Digest

logger = logging.getLogger("fleche.remote")

with ImportAlarm(
    "SshCache requires 'cloudpickle' (used for the client/server wire "
    "protocol). Install it with `pip install fleche[ssh]`.",
    raise_exception=True,
) as cloudpickle_alarm:
    import cloudpickle


# ---------------------------------------------------------------------------
# Wire protocol
# ---------------------------------------------------------------------------

_HEADER = struct.Struct(">I")


def _write_frame(stream, obj: Any) -> None:
    """Write a length-prefixed cloudpickle frame to *stream*."""
    data = cloudpickle.dumps(obj)
    stream.write(_HEADER.pack(len(data)))
    stream.write(data)
    stream.flush()


def _read_frame(stream) -> Any:
    """Read a length-prefixed cloudpickle frame from *stream*.

    Raises:
        EOFError: stream closed before a full frame was available.
    """
    header = stream.read(_HEADER.size)
    if len(header) < _HEADER.size:
        raise EOFError("connection closed before frame header")
    (n,) = _HEADER.unpack(header)
    chunks = []
    remaining = n
    while remaining > 0:
        chunk = stream.read(remaining)
        if not chunk:
            raise EOFError("connection closed mid-frame")
        chunks.append(chunk)
        remaining -= len(chunk)
    return cloudpickle.loads(b"".join(chunks))


# ---------------------------------------------------------------------------
# Server side
# ---------------------------------------------------------------------------


def _strip_cache(lc: LazyCall) -> DigestedCall:
    """Return the cache-free :class:`DigestedCall` shadow of a :class:`LazyCall`.

    The remote-bound ``_cache`` reference inside :class:`LazyCall` cannot
    travel across the wire — the client wraps the returned ``DigestedCall``
    back into a :class:`LazyCall` bound to itself via ``DigestedCall.fetch``.
    """
    return lc.detach()


def _dispatch(cache: BaseCache, method: str, args: tuple, kwargs: dict) -> Any:
    if method == "save":
        (c,) = args
        return cache.save(c)
    if method == "load":
        (key,) = args
        return _strip_cache(cache.load(key))
    if method == "load_value":
        (key,) = args
        return cache.load_value(key)
    if method == "evict":
        (key,) = args
        cache.evict(key)
        return None
    if method == "contains":
        (key,) = args
        return cache.contains(key)
    if method == "expand":
        (key,) = args
        return cache.expand(key)
    if method == "shrink":
        # Variadic: single key → Digest, multiple keys → tuple[Digest, ...].
        return cache.shrink(*args)
    if method == "query":
        (template,) = args
        return tuple(_strip_cache(lc) for lc in cache.query(template))
    raise ValueError(f"Unknown remote cache method: {method!r}")


def _is_read_only(cache: BaseCache) -> bool:
    """Best-effort check of whether *cache* will reject every ``save``.

    Recognises :class:`~fleche.caches.ReadOnlyMixin` directly (covers
    :class:`~fleche.caches.ReadOnlyCache`,
    :class:`~fleche.caches.FilteredCache`, and
    :class:`~fleche.caches.CachePool`); for a
    :class:`~fleche.caches.CacheStack` checks ``stack[0]`` since that is
    where ``CacheStack.save`` writes.  Returns ``False`` for anything
    else — at worst the client falls back to the round-trip path.
    """
    from .caches import CacheStack, ReadOnlyMixin

    if isinstance(cache, ReadOnlyMixin):
        return True
    if isinstance(cache, CacheStack):
        return bool(cache.stack) and _is_read_only(cache.stack[0])
    return False


# Config keys whose values are credentials we must not put on the wire.
# ``secret_key`` carries HMAC signing keys; ``url`` may carry a database
# password in its userinfo component (postgres / mysql).
_SENSITIVE_CONFIG_KEYS = frozenset({"secret_key"})


def _redact_url_password(url: str) -> str:
    """Replace the password component of a SQLAlchemy URL with ``"***"``.

    Plain sqlite URLs (no userinfo) round-trip unchanged.  Anything that
    doesn't parse as a URL with a userinfo component is returned as-is.
    """
    try:
        import urllib.parse as _up

        parsed = _up.urlsplit(url)
    except Exception:
        return url
    if not parsed.password:
        return url
    user = parsed.username or ""
    host_and_port = parsed.hostname or ""
    if parsed.port is not None:
        host_and_port = f"{host_and_port}:{parsed.port}"
    netloc = f"{user}:***@{host_and_port}" if user else f":***@{host_and_port}"
    return _up.urlunsplit(
        (parsed.scheme, netloc, parsed.path, parsed.query, parsed.fragment)
    )


def _redact_config(value: Any) -> Any:
    """Recursively redact credential-ish fields from a cache_to_config dict.

    Walks dicts and lists; for any dict whose key is in
    :data:`_SENSITIVE_CONFIG_KEYS`, replaces the value with
    ``"<redacted>"``.  For ``url`` keys whose value is a string with a
    password component, the password component alone is masked so the
    rest of the URL still appears in info output.
    """
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for k, v in value.items():
            if k in _SENSITIVE_CONFIG_KEYS:
                out[k] = "<redacted>"
            elif k == "url" and isinstance(v, str):
                out[k] = _redact_url_password(v)
            else:
                out[k] = _redact_config(v)
        return out
    if isinstance(value, list):
        return [_redact_config(item) for item in value]
    return value


def _server_info(cache: BaseCache, cache_name: str | None) -> dict[str, Any]:
    """Diagnostic snapshot of the server's view of itself.

    Surfaces the same things a user would `ssh host` to check by hand: which
    Python is running, in which directory, with what cache loaded.  The
    served cache config plus the CWD is usually enough to spot the common
    "remote loaded a different fleche.toml than I expected" failure mode.

    Credential fields (``secret_key``, URL passwords) are redacted by
    :func:`_redact_config` before going on the wire — the info dict is
    visible to anyone the client logs against, including the DEBUG
    ``rpc ←`` lines, and signing keys must not leak there.

    ``fleche_version`` and ``cloudpickle_version`` are exposed so the
    client can fail fast (or warn) on version skew with the server.
    The ``read_only`` flag lets the client short-circuit ``save`` and
    ``evict`` locally instead of paying a round-trip just to receive
    :class:`~fleche.caches.Rejected`.
    """
    from .config import cache_to_config

    try:
        cache_config: Any = _redact_config(cache_to_config(cache))
    except Exception as e:
        cache_config = f"<cache_to_config failed: {e}>"
    return {
        "cache": cache_config,
        "cache_name": cache_name,
        "read_only": _is_read_only(cache),
        "fleche_version": _fleche_version(),
        "cloudpickle_version": cloudpickle.__version__,
        "cwd": os.getcwd(),
        "hostname": socket.gethostname(),
        "python": sys.executable,
        "pid": os.getpid(),
    }


def _fleche_version() -> str:
    """Return the installed fleche version, or ``"unknown"`` on failure."""
    try:
        from ._version import version

        return version
    except Exception:
        return "unknown"


def serve(
    input_stream,
    output_stream,
    cache: BaseCache,
    *,
    cache_name: str | None = None,
) -> None:
    """Run the remote cache request loop until *input_stream* reaches EOF.

    Reads RPC frames from *input_stream*, dispatches them against *cache*,
    and writes responses to *output_stream*.  Exceptions from the cache are
    propagated to the client as ``("err", exception)`` frames; if an
    exception cannot be cloudpickled it is replaced with a
    :class:`RuntimeError` carrying its repr.

    Args:
        input_stream: binary readable stream (e.g. ``sys.stdin.buffer``).
        output_stream: binary writable stream (e.g. ``sys.stdout.buffer``).
        cache: the cache to serve.
        cache_name: Optional name the server was launched with — echoed back
            in ``info`` responses for debugging.
    """
    while True:
        try:
            req = _read_frame(input_stream)
        except EOFError:
            return
        try:
            method, args, kwargs = req
        except (TypeError, ValueError):
            logger.error("Malformed request frame: %r", req)
            continue
        try:
            if method == "info":
                result = _server_info(cache, cache_name)
            else:
                result = _dispatch(cache, method, args, kwargs)
            _write_frame(output_stream, ("ok", result))
        except BaseException as exc:
            try:
                _write_frame(output_stream, ("err", exc))
            except Exception:
                # exc itself failed to cloudpickle; fall back to a string.
                tb = traceback.format_exc()
                fallback = RuntimeError(f"{type(exc).__name__}: {exc}\n{tb}")
                _write_frame(output_stream, ("err", fallback))


# ---------------------------------------------------------------------------
# Client side
# ---------------------------------------------------------------------------


class RemoteConnectionError(RuntimeError):
    """Raised when the SSH subprocess cannot be reached or has died."""


def _warn_on_version_skew(info: dict[str, Any]) -> None:
    """Log a warning when the remote's fleche or cloudpickle version differs.

    The cloudpickle wire format and the fleche ``Call`` / ``LazyCall``
    schemas are tied to those library versions; a mismatch is the most
    common root cause of silently-wrong records when this PR ages.  We
    log instead of raising because forwards-compatible drift is common
    in practice (patch releases) and the user has no recourse from a
    hard failure mid-session.
    """
    local_fleche = _fleche_version()
    remote_fleche = info.get("fleche_version")
    if remote_fleche and remote_fleche != local_fleche:
        logger.warning(
            "fleche version skew: local=%s remote=%s — schemas may differ",
            local_fleche,
            remote_fleche,
        )
    local_cp = cloudpickle.__version__
    remote_cp = info.get("cloudpickle_version")
    if remote_cp and remote_cp != local_cp:
        logger.warning(
            "cloudpickle version skew: local=%s remote=%s — wire format may differ",
            local_cp,
            remote_cp,
        )


class _Connection(abc.ABC):
    """Frame-passing channel over a pair of binary streams.

    Subclasses provide :meth:`_open` (called lazily on first use) and
    optionally :meth:`_close` / :meth:`_diagnose`.  The serialised RPC
    over the channel itself is the same in every transport, so test
    transports (in-process pipes) share the request/response machinery
    with the SSH transport.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._stdin = None
        self._stdout = None
        self._opened = False
        self._atexit_registered = False

    # ------------------------------------------------------------------
    # subclass hooks
    # ------------------------------------------------------------------

    @abc.abstractmethod
    def _open(self) -> tuple:
        """Open the transport.

        Returns:
            ``(stdin, stdout)`` — a binary writable and a binary readable
            stream connecting to the remote ``serve()`` loop.
        """

    def _close(self) -> None:
        """Release any transport-level resources."""
        return None

    def _diagnose(self) -> str:
        """Return diagnostic detail to append to a connection-lost error.

        Subclasses with access to subprocess state (exit code, captured
        stderr) override this to enrich the bare EOF with whatever the
        transport can see.  The default returns an empty string.
        """
        return ""

    # ------------------------------------------------------------------
    # public API
    # ------------------------------------------------------------------

    def call(self, method: str, *args: Any, **kwargs: Any) -> Any:
        with self._lock:
            self._ensure_open()
            logger.debug("rpc → %s args=%r kwargs=%r", method, args, kwargs)
            try:
                _write_frame(self._stdin, (method, args, kwargs))
                tag, payload = _read_frame(self._stdout)
            except (BrokenPipeError, EOFError, OSError) as e:
                diag = self._diagnose()
                self._close_locked()
                msg = (
                    f"Remote cache connection lost during {method!r}: {e}\n"
                    f"Call SshCache.reconnect() to spawn a fresh subprocess."
                )
                if diag:
                    msg = f"{msg}\n{diag}"
                    logger.error("%s", msg)
                raise RemoteConnectionError(msg) from e
        logger.debug("rpc ← %s %s", method, tag)
        if tag == "ok":
            return payload
        if tag == "err":
            raise payload
        raise RuntimeError(f"Unexpected response tag from remote cache: {tag!r}")

    def reconnect(self) -> None:
        with self._lock:
            self._close_locked()

    def close(self) -> None:
        with self._lock:
            self._close_locked()

    # ------------------------------------------------------------------
    # internal
    # ------------------------------------------------------------------

    def _ensure_open(self) -> None:
        if self._opened:
            return
        self._stdin, self._stdout = self._open()
        self._opened = True
        if not self._atexit_registered:
            atexit.register(self.close)
            self._atexit_registered = True

    def _close_locked(self) -> None:
        if not self._opened:
            return
        self._opened = False
        try:
            self._close()
        except Exception:
            logger.debug("error while closing remote connection", exc_info=True)
        self._stdin = None
        self._stdout = None


class _SshConnection(_Connection):
    """Persistent ``ssh host python -m fleche remote --serve`` subprocess.

    One subprocess per :class:`SshCache` instance.  Spawned lazily on the
    first RPC and reused for the lifetime of the Python process; never
    auto-reconnected (an automatic reconnect would silently re-trigger
    interactive 2FA prompts).  :meth:`reconnect` lets the caller force a
    fresh spawn after a hang or a credential rotation.

    Stream layout:

    * **stdin / stdout** carry length-prefixed cloudpickle RPC frames
      (see :func:`_write_frame` / :func:`_read_frame`).  All cache
      operations multiplex over this single pair — there is no fan-out
      and no parallel requests; :meth:`_Connection.call` holds a lock
      across the round-trip.
    * **stderr** is drained by a daemon thread (:func:`_forward_stderr`)
      into the ``fleche.remote[<host>]`` logger at INFO and also into a
      bounded ring buffer.  When the subprocess dies, the buffer plus
      the exit code surface via :meth:`_diagnose` so the user sees the
      remote shell's last words instead of just a bare EOF.

    Command construction (:meth:`_build_command`):

    * The base command is ``ssh [ssh_options...] host``.
    * If *setup_commands* is empty, the server argv is passed directly
      so SSH ``exec``\\ s it as-is — no remote shell wraps stdin/stdout.
    * If *setup_commands* is non-empty, the snippets are joined with
      ``&&`` and prefixed in front of ``exec <server>``; the final
      ``exec`` replaces the shell so the pipe is still unwrapped.  Any
      setup failure short-circuits via ``&&`` and the SSH process exits
      non-zero — the next :func:`_read_frame` raises ``EOFError`` and
      the client surfaces the captured stderr through
      :class:`RemoteConnectionError`.
    """

    def __init__(
        self,
        host: str,
        python: str,
        cache_name: str | None,
        ssh_options: tuple[str, ...],
        setup_commands: tuple[str, ...],
        workdir: str | None = None,
    ) -> None:
        super().__init__()
        self._host = host
        self._python = python
        self._cache_name = cache_name
        self._ssh_options = ssh_options
        self._setup_commands = setup_commands
        self._workdir = workdir
        self._proc: subprocess.Popen | None = None
        self._stderr_thread: threading.Thread | None = None
        # Last few lines of remote stderr, surfaced in RemoteConnectionError
        # so REPL users see the cause without needing logging configured.
        self._stderr_buffer: collections.deque[str] = collections.deque(maxlen=50)

    def _build_command(self) -> list[str]:
        cmd = ["ssh"]
        cmd.extend(self._ssh_options)
        cmd.append(self._host)
        server_argv = [self._python, "-m", "fleche", "remote", "--serve"]
        if self._cache_name is not None:
            server_argv.extend(["--cache", self._cache_name])
        # A `cd` into the working directory runs first so the server process —
        # and the `python -m` it execs — inherits that cwd; this puts the dir
        # on sys.path so the remote can import modules referenced by unpickled
        # calls.  It precedes setup_commands in case those expect to run there.
        prefix_commands: list[str] = []
        if self._workdir is not None:
            prefix_commands.append(f"cd {shlex.quote(self._workdir)}")
        prefix_commands.extend(self._setup_commands)
        if prefix_commands:
            # Run the prefix snippets in the remote shell, then `exec` into the
            # server so stdin/stdout pipe straight through with no shell wrapper.
            # Any failure short-circuits via `&&` and the SSH process exits
            # non-zero — the client surfaces this as RemoteConnectionError.
            server_cmd = " ".join(shlex.quote(a) for a in server_argv)
            remote = " && ".join((*prefix_commands, f"exec {server_cmd}"))
            cmd.append(remote)
        else:
            cmd.extend(server_argv)
        return cmd

    def _open(self) -> tuple:
        cmd = self._build_command()
        logger.info("spawning remote cache via: %s", " ".join(cmd))
        try:
            proc = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=0,
            )
        except FileNotFoundError as e:
            raise RemoteConnectionError(f"failed to launch ssh: {e}") from e
        self._proc = proc
        self._stderr_buffer.clear()
        # Per-host child logger of `fleche.remote` (dots in host become
        # underscores so they don't create spurious sub-levels in the
        # logger hierarchy).  setLevel on `fleche.remote` cascades here.
        host_tag = self._host.replace(".", "_").replace("@", "_at_")
        self._stderr_thread = threading.Thread(
            target=_forward_stderr,
            args=(proc.stderr, f"fleche.remote.host.{host_tag}", self._stderr_buffer),
            daemon=True,
        )
        self._stderr_thread.start()
        return proc.stdin, proc.stdout

    def _diagnose(self) -> str:
        # Give the stderr forwarder a moment to drain anything written just
        # before the process died — the stderr pipe is independent of stdout
        # so its EOF and the buffer flush race the read-frame failure.
        thread = self._stderr_thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=0.5)
        parts: list[str] = []
        proc = self._proc
        if proc is not None:
            rc = proc.poll()
            if rc is not None:
                parts.append(f"remote exit code: {rc}")
        if self._stderr_buffer:
            tail = "".join(self._stderr_buffer).rstrip()
            parts.append(f"remote stderr (last {len(self._stderr_buffer)} lines):\n{tail}")
        return "\n".join(parts)

    def _close(self) -> None:
        proc = self._proc
        if proc is None:
            return
        self._proc = None
        try:
            if proc.stdin is not None:
                try:
                    proc.stdin.close()
                except Exception:
                    pass
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.terminate()
                try:
                    proc.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    proc.kill()
        finally:
            if self._stderr_thread is not None:
                self._stderr_thread.join(timeout=1.0)
                self._stderr_thread = None


def _forward_stderr(
    stream, prefix: str, buffer: "collections.deque[str] | None" = None
) -> None:
    remote_logger = logging.getLogger(prefix)
    try:
        for line in iter(stream.readline, b""):
            text = line.decode("utf-8", "replace")
            remote_logger.info("%s", text.rstrip("\n"))
            if buffer is not None:
                buffer.append(text)
    except Exception:
        pass


@dataclass(frozen=True)
class SshCache(BaseCache):
    """A cache that forwards every operation to a remote fleche over SSH.

    The remote side runs ``python -m fleche remote --serve``; its active
    cache is determined by its own ``fleche.toml`` (optionally overridden by
    *cache_name* — looked up via :func:`fleche.config.load_cache_config`).

    The SSH subprocess is spawned lazily on the first cache operation and
    reused for the lifetime of the Python process.  Set up ControlMaster /
    ControlPersist in ``~/.ssh/config`` or via *ssh_options* to share the
    underlying connection across multiple fleche runs.

    Args:
        host: SSH target, e.g. ``"user@host"`` or any alias from
            ``~/.ssh/config``.
        cache_name: Optional named cache on the remote.  ``None`` (default)
            uses the remote's default cache.
        python: Remote python executable.  Defaults to ``"python3"``.
        ssh_options: Extra command-line arguments inserted between ``ssh``
            and *host*, e.g. ``("-o", "ControlMaster=auto")``.
        setup_commands: Shell snippets run on the remote *before* the server
            process starts, joined with ``&&`` so any failure aborts the
            launch.  Typical uses are HPC environment setup —
            ``("module load python/3.11", "source ~/.venv/bin/activate")``.
            Each snippet is passed to the remote shell verbatim; quote any
            user-provided values yourself.
        workdir: Optional remote directory to ``cd`` into before launching the
            server.  Because the server starts the cache via ``python -m``, the
            working directory lands on ``sys.path``, so setting it lets the
            remote import the local modules referenced by unpickled calls (the
            "fudge imports" use case).  The ``cd`` runs ahead of
            *setup_commands*.
    """

    host: str
    cache_name: str | None = None
    python: str = "python3"
    ssh_options: tuple[str, ...] = ()
    setup_commands: tuple[str, ...] = ()
    workdir: str | None = None
    _conn: _Connection = field(init=False, repr=False, compare=False, hash=False)
    _info_cache: "dict[str, Any] | None" = field(
        init=False, default=None, repr=False, compare=False, hash=False
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "ssh_options", tuple(self.ssh_options))
        object.__setattr__(self, "setup_commands", tuple(self.setup_commands))
        conn = _SshConnection(
            host=self.host,
            python=self.python,
            cache_name=self.cache_name,
            ssh_options=self.ssh_options,
            setup_commands=self.setup_commands,
            workdir=self.workdir,
        )
        object.__setattr__(self, "_conn", conn)

    # ------------------------------------------------------------------
    # BaseCache surface
    # ------------------------------------------------------------------

    def _ensure_handshake(self) -> None:
        """Trigger the lazy version handshake (idempotent).

        Called at the top of every BaseCache method so the first RPC of
        a session implicitly fetches the server's info dict, which both
        populates the read-only short-circuit cache and runs the
        fleche/cloudpickle version-skew check via
        :func:`_warn_on_version_skew`.  Subsequent ops are zero-cost.
        """
        if self._info_cache is None:
            self._cached_info()

    def save(self, call: Call) -> str:
        self._ensure_handshake()
        if self._info_cache and self._info_cache.get("read_only", False):
            raise Rejected(self, call)
        return self._conn.call("save", call)

    def load(self, key: str) -> LazyCall:
        self._ensure_handshake()
        dc: DigestedCall = self._conn.call("load", key)
        return dc.fetch(self)

    def load_value(self, key: str) -> Any:
        self._ensure_handshake()
        return self._conn.call("load_value", key)

    def evict(self, key: str | Digest) -> None:
        self._ensure_handshake()
        if self._info_cache and self._info_cache.get("read_only", False):
            raise Rejected("Cannot evict from a read-only remote cache", self, key)
        self._conn.call("evict", key)

    def contains(self, key: str) -> bool:
        self._ensure_handshake()
        return self._conn.call("contains", key)

    def expand(self, key: Digest | str) -> Digest:
        self._ensure_handshake()
        return self._conn.call("expand", key)

    def _shrink(self, *keys: Digest | str) -> "tuple[Digest, ...]":
        self._ensure_handshake()
        if len(keys) == 1:
            return (self._conn.call("shrink", keys[0]),)
        return self._conn.call("shrink", *keys)

    def _query(self, call: QueryCall) -> Iterable[LazyCall]:
        self._ensure_handshake()
        results: tuple[DigestedCall, ...] = self._conn.call("query", call)
        for dc in results:
            yield dc.fetch(self)

    # ------------------------------------------------------------------
    # lifecycle helpers
    # ------------------------------------------------------------------

    def reconnect(self) -> None:
        """Drop the current SSH subprocess; the next operation reconnects.

        Useful if the underlying transport hangs or the remote needs to be
        re-authenticated.  Not invoked automatically — auto-reconnect would
        silently re-trigger 2FA prompts.
        """
        # Cached info reflects the *previous* server process — invalidate so
        # the next `read_only` check re-fetches against whatever is on the
        # other end of the new subprocess.
        object.__setattr__(self, "_info_cache", None)
        self._conn.reconnect()

    def close(self) -> None:
        """Close the SSH subprocess if it is currently open."""
        self._conn.close()

    # ------------------------------------------------------------------
    # debug helpers
    # ------------------------------------------------------------------

    @property
    def read_only(self) -> bool:
        """Whether the remote cache will reject every ``save`` / ``evict``.

        Read from the cached server info (one ``info`` RPC on first
        access, then reused for the lifetime of the connection). Used to
        short-circuit ``save`` and ``evict`` locally so the client
        doesn't pay a round-trip just to receive
        :class:`~fleche.caches.Rejected`.
        """
        return self._cached_info().get("read_only", False)

    def info(self, *, refresh: bool = True) -> dict[str, Any]:
        """Return a snapshot of the remote server's view of itself.

        Keys: ``cache`` (the served cache serialised via
        :func:`fleche.config.cache_to_config` — a structured dict that
        round-trips through :func:`~fleche.config.cache_from_config`,
        with credential fields like ``secret_key`` and URL passwords
        redacted server-side), ``cache_name`` (the ``--cache`` argument
        the server was launched with, if any), ``read_only`` (whether
        saves/evicts will be rejected), ``fleche_version``,
        ``cloudpickle_version``, ``cwd``, ``hostname``, ``python``,
        ``pid``.

        Primary use: any "the remote isn't doing what I expected"
        question (wrong cache, wrong cwd, surprising read_only,
        surprising Python).  The first lazy fetch also drives the
        version handshake — see :meth:`_cached_info`.

        Args:
            refresh: When True (default), make a fresh ``info`` RPC and
                update the local cache.  When False, return the cached
                copy if one exists (fetching on first call).
        """
        info = self._info_cache
        if refresh or info is None:
            info = self._conn.call("info")
            object.__setattr__(self, "_info_cache", info)
            _warn_on_version_skew(info)
        return info

    def _cached_info(self) -> dict[str, Any]:
        """Internal accessor: fetch info once, then reuse it.

        The first fetch doubles as a version handshake — see
        :func:`_warn_on_version_skew`.  Any RPC method that
        short-circuits on the cached info (currently ``save`` /
        ``evict`` via the ``read_only`` flag) therefore implicitly
        triggers the handshake on its first call.
        """
        if self._info_cache is None:
            return self.info(refresh=False)
        return self._info_cache


# ---------------------------------------------------------------------------
# Server entry point: invoked by `python -m fleche remote --serve` via
# `fleche.__main__`.  Not exposed as `__main__` here because the package's
# `__init__` transitively imports `fleche.remote`, so running this file
# directly would trigger the `runpy` double-import warning.
# ---------------------------------------------------------------------------


def _run_server(cache_name: str | None) -> int:
    """Load *cache_name* (or the default) and run :func:`serve` over stdio.

    Installs the requested cache as the *active* one (via the ContextVar in
    :mod:`fleche.state`) so anything executed inside the served cache —
    metadata hooks, value-loading through ``LazyCall`` references, nested
    ``@fleche()`` calls — sees the same cache the RPC layer is dispatching
    against.  ``load_cache_config()`` alone only constructs the cache; it
    doesn't activate it.
    """
    from . import cache as activate_cache

    if cache_name is not None:
        activate_cache(cache_name)
    cache = activate_cache()
    logger.info("serving remote fleche cache (name=%r): %r", cache_name, cache)
    serve(sys.stdin.buffer, sys.stdout.buffer, cache, cache_name=cache_name)
    return 0


__all__ = [
    "RemoteConnectionError",
    "SshCache",
    "serve",
]
