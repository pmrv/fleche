"""Unit tests for :mod:`fleche.remote`.

These tests drive the server loop in a background thread with ``os.pipe()``
streams in place of an SSH subprocess.  The same wire protocol is exercised;
only the transport is swapped.
"""

import dataclasses
import io
import os
import sys
import threading
import types
from typing import Any

import pytest

import fleche.state as _state
from fleche.call import Call, QueryCall
from fleche.caches import Cache, Rejected
from fleche.config import cache_to_config, load_cache_config
from fleche.digest import Digest, digest
from fleche.remote import (
    RemoteConnectionError,
    RemotePathUnsupported,
    SshCache,
    _Connection,
    _dispatch,
    _read_frame,
    _run_server,
    _REMOTE_METHODS,
    _write_frame,
    serve,
)
from fleche.storage import CallMemory, SaveError, ValueMemory


class _PipeConnection(_Connection):
    """In-process transport for tests: run ``serve()`` in a thread.

    Two ``os.pipe()`` pairs connect the client's write/read to the server's
    read/write.  No SSH involved.
    """

    def __init__(self, cache):
        super().__init__()
        self._cache = cache
        self._thread = None
        self._server_stdin = None
        self._server_stdout = None

    def _open(self):
        server_in_r, client_out_w = os.pipe()
        client_in_r, server_out_w = os.pipe()
        client_stdin = os.fdopen(client_out_w, "wb", buffering=0)
        client_stdout = os.fdopen(client_in_r, "rb", buffering=0)
        self._server_stdin = os.fdopen(server_in_r, "rb", buffering=0)
        self._server_stdout = os.fdopen(server_out_w, "wb", buffering=0)
        self._thread = threading.Thread(
            target=serve,
            args=(self._server_stdin, self._server_stdout, self._cache),
            daemon=True,
        )
        self._thread.start()
        return client_stdin, client_stdout

    def _close(self):
        # Closing client's stdin signals EOF on server's stdin -> serve() returns.
        for s in (self._stdin, self._stdout):
            try:
                if s is not None:
                    s.close()
            except Exception:
                pass
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None
        for s in (self._server_stdin, self._server_stdout):
            try:
                if s is not None:
                    s.close()
            except Exception:
                pass
        self._server_stdin = None
        self._server_stdout = None


def _make_remote(cache):
    """Return an :class:`SshCache` whose connection is an in-process pipe."""
    sc = SshCache(host="test-host")
    object.__setattr__(sc, "_conn", _PipeConnection(cache))
    return sc


@pytest.fixture
def server_cache():
    return Cache(ValueMemory({}), CallMemory({}))


@pytest.fixture
def remote(server_cache):
    sc = _make_remote(server_cache)
    yield sc
    sc.close()


# ---------------------------------------------------------------------------
# Frame protocol
# ---------------------------------------------------------------------------


def test_frame_round_trip():
    buf = io.BytesIO()
    payload = ("hello", {"a": 1, "b": [1, 2, 3]}, None)
    _write_frame(buf, payload)
    buf.seek(0)
    assert _read_frame(buf) == payload


def test_frame_eof_raises():
    with pytest.raises(EOFError):
        _read_frame(io.BytesIO())


def test_frame_truncated_raises():
    buf = io.BytesIO()
    _write_frame(buf, ("x" * 100,))
    buf.truncate(8)  # half a header + nothing
    buf.seek(0)
    with pytest.raises(EOFError):
        _read_frame(buf)


# ---------------------------------------------------------------------------
# BaseCache surface
# ---------------------------------------------------------------------------


def test_save_and_load(remote, server_cache):
    c = Call(name="f", arguments={"x": 1}, result=42)
    key = remote.save(c)
    # The remote cache actually holds the data.
    assert server_cache.contains(key)
    # The client can load it back through the SSH layer.
    lc = remote.load(key)
    assert lc.result == 42
    assert dict(lc.arguments) == {"x": 1}


def test_contains_miss(remote):
    assert remote.contains("0" * 64) is False


def test_load_value(remote):
    c = Call(name="f", arguments={"x": 7}, result="hello")
    remote.save(c)
    # The result digest is content-addressed; load_value pulls bytes back.
    # We don't know the digest a priori — use query() to discover it.
    [lc] = list(remote.query(name="f"))
    assert lc.result == "hello"


def test_evict(remote, server_cache):
    c = Call(name="f", arguments={"x": 1}, result=99)
    key = remote.save(c)
    assert server_cache.contains(key)
    remote.evict(key)
    assert not server_cache.contains(key)


def test_load_missing_raises_keyerror(remote):
    with pytest.raises(KeyError):
        remote.load("0" * 64)


def test_query_returns_lazy_calls(remote):
    keys = []
    for x in range(3):
        keys.append(remote.save(Call(name="f", arguments={"x": x}, result=x * 2)))
    results = list(remote.query(name="f"))
    assert len(results) == 3
    by_x = {lc.arguments["x"]: lc.result for lc in results}
    assert by_x == {0: 0, 1: 2, 2: 4}


def test_query_lazy_load_value_round_trips(remote):
    """``LazyCall._cache`` should point at the client, not the server."""
    remote.save(Call(name="f", arguments={"x": 5}, result="payload"))
    [lc] = list(remote.query(name="f"))
    # Accessing result triggers another RPC via the client cache.
    assert lc.result == "payload"


def test_expand_and_shrink(remote):
    key = remote.save(Call(name="g", arguments={"a": 1}, result=1))
    expanded = remote.expand(key[:8])
    assert expanded == key
    shrunk = remote.shrink(key)
    assert key.startswith(shrunk)


def test_shrink_variadic(remote):
    """shrink(*keys): single key → Digest, multiple → tuple in order."""
    k1 = remote.save(Call(name="g", arguments={"a": 1}, result=1))
    k2 = remote.save(Call(name="g", arguments={"a": 2}, result=2))
    # Single key returns a scalar Digest.
    single = remote.shrink(k1)
    assert isinstance(single, str)
    assert k1.startswith(single)
    # Multiple keys return a tuple in input order.
    many = remote.shrink(k1, k2)
    assert isinstance(many, tuple)
    assert len(many) == 2
    assert k1.startswith(many[0])
    assert k2.startswith(many[1])


# ---------------------------------------------------------------------------
# _dispatch registry
# ---------------------------------------------------------------------------


def test_dispatch_unknown_method_raises_valueerror():
    cache = Cache(ValueMemory({}), CallMemory({}))
    with pytest.raises(ValueError, match="Unknown remote cache method: 'nope'"):
        _dispatch(cache, "nope", (), {})


def test_dispatch_covers_every_registered_method():
    """Every name a client stub calls must have a registry entry."""
    assert set(_REMOTE_METHODS) == {
        "save",
        "load",
        "load_value",
        "save_value",
        "evict",
        "contains",
        "expand",
        "shrink",
        "query",
    }


def test_dispatch_evict_is_void_even_if_cache_returns_a_value(monkeypatch):
    """`evict`'s return value is not part of the wire contract (regression for #638):
    a registry entry that forgot `void=True` would leak it across the wire."""
    cache = Cache(ValueMemory({}), CallMemory({}))
    monkeypatch.setattr(Cache, "evict", lambda self, key: "not-none")
    assert _dispatch(cache, "evict", ("deadbeef",), {}) is None


# ---------------------------------------------------------------------------
# Error propagation
# ---------------------------------------------------------------------------


def test_keyerror_propagates(remote):
    # An empty cache has no entries to match a short prefix, so expand
    # raises KeyError; the exception must travel back across the wire.
    with pytest.raises(KeyError):
        remote.expand("deadbeef")


def test_rejected_propagates():
    """A server-side ``Rejected`` arrives at the client as ``Rejected``."""
    server = Cache(ValueMemory({}), CallMemory({})).readonly()
    sc = _make_remote(server)
    try:
        with pytest.raises(Rejected):
            sc.save(Call(name="f", arguments={}, result=1))
    finally:
        sc.close()


def test_read_only_short_circuits_save_and_evict():
    """`save`/`evict` against a read-only remote raise locally, no RPC."""
    server = Cache(ValueMemory({}), CallMemory({})).readonly()
    sc = _make_remote(server)
    try:
        # Trigger the info fetch once so the read_only flag is cached.
        assert sc.read_only is True

        # Now spy on the connection: any further RPC means we failed to
        # short-circuit.  `save` and `evict` should raise without
        # touching the wire.
        rpc_calls = []
        original_call = sc._conn.call

        def spy(method, *args, **kwargs):
            rpc_calls.append(method)
            return original_call(method, *args, **kwargs)

        sc._conn.call = spy  # type: ignore[method-assign]

        with pytest.raises(Rejected):
            sc.save(Call(name="f", arguments={}, result=1))
        with pytest.raises(Rejected):
            sc.evict("deadbeef")
        assert rpc_calls == [], f"unexpected RPCs: {rpc_calls}"
    finally:
        sc.close()


def test_read_only_false_for_writable_remote(remote):
    """A normal remote cache reports `read_only == False`."""
    assert remote.read_only is False


def test_reconnect_invalidates_info_cache(remote, server_cache):
    """`reconnect()` drops the cached info so the next read re-fetches."""
    info1 = remote.info()
    pid1 = info1["pid"]
    assert remote._info_cache is not None
    remote.reconnect()
    assert remote._info_cache is None
    # First post-reconnect read_only access re-populates the cache.
    _ = remote.read_only
    assert remote._info_cache is not None
    # Same in-process server thread → same pid; the point is the
    # cache was repopulated, not its content.
    assert remote._info_cache["pid"] == pid1


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------


def test_reconnect_reopens_subprocess(remote, server_cache):
    key = remote.save(Call(name="f", arguments={"x": 1}, result=1))
    remote.reconnect()
    # After reconnect a new server thread is running against a *fresh* cache
    # in our test fixture — wait, actually the fixture reuses server_cache,
    # so the data should still be there.
    assert remote.contains(key)


def test_close_is_idempotent(remote):
    remote.close()
    remote.close()


# ---------------------------------------------------------------------------
# Diagnostics on connection drop
# ---------------------------------------------------------------------------


class _DeadConnection(_Connection):
    """Transport whose 'server' is already EOF — first call raises immediately."""

    def __init__(self, diag: str = ""):
        super().__init__()
        self._diag = diag

    def _open(self):
        # Write side has no reader; read side is already at EOF.
        client_in_r, _server_out_w = os.pipe()
        os.close(_server_out_w)
        _server_in_r, client_out_w = os.pipe()
        os.close(_server_in_r)
        stdin = os.fdopen(client_out_w, "wb", buffering=0)
        stdout = os.fdopen(client_in_r, "rb", buffering=0)
        return stdin, stdout

    def _diagnose(self) -> str:
        return self._diag


def test_connection_drop_includes_diagnose_output():
    """When the remote dies, the diagnose() string is part of the error."""
    from fleche.remote import RemoteConnectionError

    conn = _DeadConnection(diag="remote exit code: 127\nmodule: command not found")
    with pytest.raises(RemoteConnectionError) as excinfo:
        conn.call("contains", "abc")
    msg = str(excinfo.value)
    assert "Remote cache connection lost during 'contains'" in msg
    assert "SshCache.reconnect()" in msg
    assert "remote exit code: 127" in msg
    assert "module: command not found" in msg


def test_connection_drop_without_diagnose_keeps_old_message():
    """Empty _diagnose() (base default) leaves the error message unchanged."""
    from fleche.remote import RemoteConnectionError

    conn = _DeadConnection(diag="")
    with pytest.raises(RemoteConnectionError) as excinfo:
        conn.call("contains", "abc")
    msg = str(excinfo.value)
    assert "Remote cache connection lost during 'contains'" in msg
    assert "SshCache.reconnect()" in msg
    # No spurious blank lines appended.
    assert not msg.endswith("\n")


def test_info_round_trip(remote, server_cache):
    """`SshCache.info()` returns the server's self-snapshot."""
    from fleche.config import cache_to_config

    info = remote.info()
    assert info["cache"] == cache_to_config(server_cache)
    assert info["cwd"] == os.getcwd()
    assert isinstance(info["hostname"], str) and info["hostname"]
    assert info["python"] == sys.executable
    assert info["pid"] == os.getpid()
    # cache_name is None in the test rig (the in-process serve() takes no arg).
    assert info["cache_name"] is None


def test_info_echoes_cache_name():
    """`serve(..., cache_name=...)` makes the name visible to info()."""
    import sys as _sys

    server = Cache(ValueMemory({}), CallMemory({}))
    sc = SshCache(host="test-host")

    class _NamedPipe(_PipeConnection):
        def _open(self):
            import os as _os

            server_in_r, client_out_w = _os.pipe()
            client_in_r, server_out_w = _os.pipe()
            client_stdin = _os.fdopen(client_out_w, "wb", buffering=0)
            client_stdout = _os.fdopen(client_in_r, "rb", buffering=0)
            self._server_stdin = _os.fdopen(server_in_r, "rb", buffering=0)
            self._server_stdout = _os.fdopen(server_out_w, "wb", buffering=0)
            self._thread = threading.Thread(
                target=serve,
                args=(self._server_stdin, self._server_stdout, self._cache),
                kwargs={"cache_name": "myname"},
                daemon=True,
            )
            self._thread.start()
            return client_stdin, client_stdout

    object.__setattr__(sc, "_conn", _NamedPipe(server))
    try:
        assert sc.info()["cache_name"] == "myname"
    finally:
        sc.close()


# ---------------------------------------------------------------------------
# Info redaction and version handshake
# ---------------------------------------------------------------------------


def test_info_redacts_secret_key():
    """`secret_key` in the served cache config must not leak via info()."""
    from fleche.remote import _redact_config

    # Direct test of the redactor — independent of the in-process server.
    raw = {
        "values": {"type": "cloudpickle", "root": "/x", "secret_key": ["a" * 64]},
        "calls": {"type": "cloudpickle", "root": "/y", "secret_key": ["b" * 64]},
    }
    redacted = _redact_config(raw)
    assert redacted["values"]["secret_key"] == "<redacted>"
    assert redacted["calls"]["secret_key"] == "<redacted>"
    # Non-sensitive fields pass through.
    assert redacted["values"]["root"] == "/x"


def test_info_redacts_url_password():
    """URL passwords in non-sqlite SQL configs are masked."""
    from fleche.remote import _redact_url_password

    assert (
        _redact_url_password("postgresql://alice:hunter2@db.example.com:5432/x")
        == "postgresql://alice:***@db.example.com:5432/x"
    )
    # No password component → pass through.
    assert (
        _redact_url_password("sqlite:///tmp/foo.db")
        == "sqlite:///tmp/foo.db"
    )
    assert (
        _redact_url_password("postgresql://alice@db.example.com/x")
        == "postgresql://alice@db.example.com/x"
    )


def test_redact_config_walks_stack_with_nested_sql_url():
    """`_redact_config` recurses through list-shaped stack configs and masks nested SQL URLs.

    :func:`cache_to_config` serialises a :class:`~fleche.caches.CacheStack` as a
    top-level list of member dicts.  A member with a :class:`~fleche.storage.sql.Sql`
    call storage carries the DB password inside its nested ``calls.url``.  Both
    the list traversal (recursion into each member) and the nested ``url``
    rewrite must fire for a stack-of-SQL-caches ``info()`` handshake not to leak
    the password.  The primitives are exercised in isolation by
    ``test_info_redacts_secret_key`` / ``test_info_redacts_url_password``; this
    test pins their composition on the shape that ends up on the wire.
    """
    from fleche.remote import _redact_config

    stack_config = [
        {
            "values": {"type": "memory"},
            "calls": {
                "type": "sql",
                "url": "postgresql://alice:hunter2@db.example.com:5432/x",
            },
        },
        {
            "values": {"type": "memory"},
            "calls": {"type": "memory"},
        },
    ]
    redacted = _redact_config(stack_config)
    assert isinstance(redacted, list)
    assert len(redacted) == 2
    assert (
        redacted[0]["calls"]["url"]
        == "postgresql://alice:***@db.example.com:5432/x"
    )
    assert redacted[1]["calls"] == {"type": "memory"}


def test_info_exposes_versions(remote):
    """info() includes `fleche_version` and `cloudpickle_version`."""
    info = remote.info()
    assert "fleche_version" in info
    assert "cloudpickle_version" in info
    # Same process, same versions.
    import cloudpickle as _cp
    from fleche.remote import _fleche_version

    assert info["fleche_version"] == _fleche_version()
    assert info["cloudpickle_version"] == _cp.__version__


def test_version_skew_logs_warning(remote, caplog):
    """Mismatched fleche/cloudpickle versions in info trigger a warning."""
    import logging
    from fleche.remote import _warn_on_version_skew

    caplog.set_level(logging.WARNING, logger="fleche.remote")
    _warn_on_version_skew(
        {"fleche_version": "999.0.0", "cloudpickle_version": "999.0"}
    )
    msgs = [r.getMessage() for r in caplog.records]
    assert any("fleche version skew" in m for m in msgs)
    assert any("cloudpickle version skew" in m for m in msgs)


def test_handshake_runs_on_first_op(remote, server_cache):
    """The first BaseCache method drives the handshake (populates info cache)."""
    assert remote._info_cache is None
    remote.contains("deadbeef")  # any op
    assert remote._info_cache is not None
    assert "fleche_version" in remote._info_cache


def test_forward_stderr_appends_to_buffer():
    """The stderr forwarder mirrors lines into the diagnostic buffer."""
    import collections as _c
    from fleche.remote import _forward_stderr

    buf: _c.deque[str] = _c.deque(maxlen=5)
    stream = io.BytesIO(b"module: command not found\nbash: line 1: oops\n")
    _forward_stderr(stream, "test.remote", buf)
    assert list(buf) == ["module: command not found\n", "bash: line 1: oops\n"]


# ---------------------------------------------------------------------------
# Server-side error recovery
# ---------------------------------------------------------------------------
#
# ``serve()`` documents two error-recovery contracts:
#
#   1. A frame whose payload isn't ``(method, args, kwargs)`` is logged and
#      skipped; the loop keeps reading subsequent frames instead of dying.
#   2. If a cache-raised exception cannot be cloudpickled, the server replaces
#      it with a ``RuntimeError`` carrying its repr + traceback so the client
#      always receives an ``("err", ...)`` frame instead of a wire-protocol
#      error (which would surface as a bare ``EOFError`` on the client).
#
# Both branches are exercised in-process by piping pre-built request bytes
# through ``serve()`` and inspecting the responses it writes back.


def test_serve_malformed_frame_is_skipped_and_loop_continues(caplog):
    """A non-tuple request is logged as malformed; the next well-formed
    frame is still handled, so a noisy client can't wedge the server."""
    import logging

    server_in = io.BytesIO()
    _write_frame(server_in, "not a tuple")          # malformed
    _write_frame(server_in, ("contains", ("0" * 64,), {}))  # well-formed
    server_in.seek(0)
    server_out = io.BytesIO()

    cache = Cache(ValueMemory({}), CallMemory({}))
    caplog.set_level(logging.ERROR, logger="fleche.remote")
    serve(server_in, server_out, cache)

    assert any(
        "Malformed request frame" in r.getMessage() for r in caplog.records
    ), "expected the malformed frame to be logged"

    # Exactly one response written — for the second, well-formed frame.
    server_out.seek(0)
    tag, payload = _read_frame(server_out)
    assert tag == "ok"
    assert payload is False  # `contains` misses on an empty cache
    with pytest.raises(EOFError):
        _read_frame(server_out)


def test_serve_falls_back_when_exception_is_unpicklable(monkeypatch):
    """Cache exceptions that can't be cloudpickled are wrapped in a
    ``RuntimeError`` so an ``("err", ...)`` frame is always delivered."""
    from fleche import remote as _remote

    class Unpicklable(RuntimeError):
        def __reduce__(self):
            raise TypeError("this exception cannot travel across the wire")

    def raising_dispatch(cache, method, args, kwargs):
        raise Unpicklable("boom")

    monkeypatch.setattr(_remote, "_dispatch", raising_dispatch)

    server_in = io.BytesIO()
    _write_frame(server_in, ("contains", ("0" * 64,), {}))
    server_in.seek(0)
    server_out = io.BytesIO()

    cache = Cache(ValueMemory({}), CallMemory({}))
    serve(server_in, server_out, cache)

    server_out.seek(0)
    tag, payload = _read_frame(server_out)
    assert tag == "err"
    # The fallback replaces the un-cloudpicklable exception with a plain
    # RuntimeError carrying enough context for a human to diagnose it.
    assert isinstance(payload, RuntimeError)
    assert not isinstance(payload, Unpicklable)
    msg = str(payload)
    assert "Unpicklable" in msg
    assert "boom" in msg


# ---------------------------------------------------------------------------
# Config integration
# ---------------------------------------------------------------------------


def test_cache_from_config_builds_sshcache():
    from fleche.config import cache_from_config

    c = cache_from_config(
        {
            "type": "ssh",
            "host": "user@example.com",
            "cache_name": "shared",
            "python": "python3.12",
            "ssh_options": ["-o", "ControlMaster=auto"],
        }
    )
    assert isinstance(c, SshCache)
    assert c.host == "user@example.com"
    assert c.cache_name == "shared"
    assert c.python == "python3.12"
    assert c.ssh_options == ("-o", "ControlMaster=auto")
    c.close()


def test_cache_to_config_round_trip():
    from fleche.config import cache_from_config, cache_to_config

    original = {
        "type": "ssh",
        "host": "user@example.com",
        "cache_name": "shared",
        "ssh_options": ["-o", "ControlMaster=auto"],
    }
    c = cache_from_config(original)
    try:
        d = cache_to_config(c)
    finally:
        c.close()
    assert d["type"] == "ssh"
    assert d["host"] == "user@example.com"
    assert d["cache_name"] == "shared"
    assert d["ssh_options"] == ["-o", "ControlMaster=auto"]


def test_sshcache_default_command_has_no_shell_wrapper():
    """Without setup_commands, args are passed as a list — no shell parsing."""
    c = SshCache(host="user@example.com", cache_name="shared")
    try:
        cmd = c._conn._build_command()
    finally:
        c.close()
    assert cmd[:2] == ["ssh", "user@example.com"]
    assert cmd[2:] == ["python3", "-m", "fleche", "remote", "--serve", "--cache", "shared"]


def test_sshcache_setup_commands_prefixed_with_exec():
    """setup_commands run via the remote shell and `exec` into the server."""
    c = SshCache(
        host="user@example.com",
        cache_name="shared",
        setup_commands=("module load python/3.11", "source ~/.venv/bin/activate"),
    )
    try:
        cmd = c._conn._build_command()
    finally:
        c.close()
    assert cmd[:2] == ["ssh", "user@example.com"]
    assert len(cmd) == 3, f"setup_commands should collapse into one shell arg, got {cmd!r}"
    remote = cmd[2]
    assert remote.startswith("module load python/3.11 && source ~/.venv/bin/activate && exec ")
    # The server invocation is shell-quoted so paths with spaces survive.
    assert "python3 -m fleche remote --serve --cache shared" in remote


def test_sshcache_setup_commands_config_round_trip():
    from fleche.config import cache_from_config, cache_to_config

    original = {
        "type": "ssh",
        "host": "user@example.com",
        "setup_commands": ["module load python/3.11", "source ~/.venv/bin/activate"],
    }
    c = cache_from_config(original)
    try:
        assert c.setup_commands == (
            "module load python/3.11",
            "source ~/.venv/bin/activate",
        )
        d = cache_to_config(c)
    finally:
        c.close()
    assert d["setup_commands"] == [
        "module load python/3.11",
        "source ~/.venv/bin/activate",
    ]


def test_sshcache_setup_commands_omitted_from_config_when_empty():
    from fleche.config import cache_to_config

    c = SshCache(host="user@example.com")
    try:
        d = cache_to_config(c)
    finally:
        c.close()
    assert "setup_commands" not in d


def test_sshcache_workdir_cds_before_exec():
    """workdir prepends a `cd` ahead of the server exec."""
    c = SshCache(
        host="user@example.com",
        cache_name="shared",
        workdir="~/my project",
    )
    try:
        cmd = c._conn._build_command()
    finally:
        c.close()
    assert cmd[:2] == ["ssh", "user@example.com"]
    assert len(cmd) == 3, f"workdir should collapse into one shell arg, got {cmd!r}"
    remote = cmd[2]
    # The workdir is shell-quoted so paths with spaces survive.
    assert remote.startswith("cd '~/my project' && exec ")
    assert "python3 -m fleche remote --serve --cache shared" in remote


def test_sshcache_workdir_runs_before_setup_commands():
    """The `cd` precedes setup_commands in the combined shell snippet."""
    c = SshCache(
        host="user@example.com",
        workdir="/opt/project",
        setup_commands=("source ~/.venv/bin/activate",),
    )
    try:
        cmd = c._conn._build_command()
    finally:
        c.close()
    remote = cmd[2]
    assert remote.startswith("cd /opt/project && source ~/.venv/bin/activate && exec ")


def test_sshcache_workdir_config_round_trip():
    from fleche.config import cache_from_config, cache_to_config

    original = {
        "type": "ssh",
        "host": "user@example.com",
        "workdir": "~/project",
    }
    c = cache_from_config(original)
    try:
        assert c.workdir == "~/project"
        d = cache_to_config(c)
    finally:
        c.close()
    assert d["workdir"] == "~/project"


def test_sshcache_workdir_omitted_from_config_when_unset():
    from fleche.config import cache_to_config

    c = SshCache(host="user@example.com")
    try:
        d = cache_to_config(c)
    finally:
        c.close()
    assert "workdir" not in d


# ---------------------------------------------------------------------------
# Real subprocess lifecycle (covers _SshConnection._open / _diagnose / _close)
# ---------------------------------------------------------------------------


def test_sshconnection_surfaces_remote_exit_code_and_stderr_tail():
    """Real-subprocess failure surfaces exit code + stderr tail to the caller.

    All other tests stub the transport with in-process pipes, so the
    :class:`_SshConnection` lifecycle (spawn, stderr forwarder, diagnose,
    teardown) is otherwise unexercised. Here we substitute the SSH argv
    with a local Python one-liner that writes to stderr and exits
    non-zero, then drive a single RPC: the resulting
    :class:`RemoteConnectionError` must carry the exit code and stderr
    tail produced by :meth:`_SshConnection._diagnose`. This is the
    user-visible promise that a failed ``module load`` / missing remote
    venv shows up as a useful error instead of a bare ``EOFError``.
    """
    from fleche.remote import RemoteConnectionError, _SshConnection

    script = (
        "import sys\n"
        "sys.stderr.write('module: command not found\\n')\n"
        "sys.stderr.flush()\n"
        "sys.exit(7)\n"
    )

    class _LocalSubprocess(_SshConnection):
        def _build_command(self):
            return [sys.executable, "-c", script]

    conn = _LocalSubprocess(
        host="local.host",
        python=sys.executable,
        cache_name=None,
        ssh_options=(),
        setup_commands=(),
    )
    try:
        with pytest.raises(RemoteConnectionError) as excinfo:
            conn.call("contains", "deadbeef")
    finally:
        conn.close()
    msg = str(excinfo.value)
    assert "Remote cache connection lost during 'contains'" in msg
    assert "remote exit code: 7" in msg
    assert "module: command not found" in msg
    # _close() drops the proc and the stderr thread.
    assert conn._proc is None
    assert conn._stderr_thread is None


def test_cache_stack_with_ssh_layer():
    """A stack of [local, ssh] composes via the existing array-of-tables path."""
    from fleche.config import cache_from_config
    from fleche.caches import CacheStack

    c = cache_from_config(
        [
            {"values": {"type": "memory"}, "calls": {"type": "memory"}},
            {"type": "ssh", "host": "user@example.com"},
        ]
    )
    assert isinstance(c, CacheStack)
    assert isinstance(c.stack[1], SshCache)
    c.stack[1].close()


# ---------------------------------------------------------------------------
# `_run_server` — the `python -m fleche remote --serve` entry point
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("cache_name", [None, "memory"])
def test_run_server_serves_active_cache_over_stdio_until_eof(monkeypatch, cache_name):
    """``_run_server`` is the entry point invoked by ``python -m fleche
    remote --serve``: it activates the named cache (when given), runs
    :func:`serve` over ``sys.stdin.buffer`` / ``sys.stdout.buffer``, and
    returns ``0`` on clean stdin EOF.

    The integration tests exercise this through a real subprocess where
    coverage doesn't propagate to the parent run, so this drives the
    function in-process with stubbed binary stdio streams. The single
    ``info`` request preloaded into the fake stdin lets us verify two
    contracts in one round-trip: the served cache matches the one
    selected by ``cache_name`` (``None`` → the active cache as it stood
    on entry; ``"memory"`` → the named cache installed via
    :func:`fleche.state.cache`), and ``cache_name`` is echoed back so a
    server launched with ``--cache NAME`` is recognisable from the
    client's ``info()``.
    """
    fake_stdin = io.BytesIO()
    _write_frame(fake_stdin, ("info", (), {}))
    fake_stdin.seek(0)
    fake_stdout = io.BytesIO()
    monkeypatch.setattr(sys, "stdin", types.SimpleNamespace(buffer=fake_stdin))
    monkeypatch.setattr(sys, "stdout", types.SimpleNamespace(buffer=fake_stdout))

    # Pin a freshly-constructed clean cache as active.  Two reasons:
    # (1) `_run_server(cache_name)` calls `cache(cache_name)` which mutates
    # the active-cache ContextVar stickily — without a token reset the change
    # leaks into subsequent tests; (2) ``cache_to_config`` recurses into a
    # ``MemoryBackend.storage`` dict via ``dataclasses.asdict``, so an active
    # cache left populated by earlier tests would make the round-trip
    # comparison below crash on unrelated state.
    clean_cache = Cache(ValueMemory({}), CallMemory({}))
    cache_token = _state._CACHE.set(clean_cache)
    try:
        assert _run_server(cache_name=cache_name) == 0
    finally:
        _state._CACHE.reset(cache_token)

    fake_stdout.seek(0)
    tag, info = _read_frame(fake_stdout)
    assert tag == "ok"
    assert info["cache_name"] == cache_name
    expected_cache = (
        load_cache_config(cache_name) if cache_name is not None else clean_cache
    )
    assert info["cache"] == cache_to_config(expected_cache)
    # Clean EOF: no second frame queued.
    assert fake_stdout.read() == b""


# ---------------------------------------------------------------------------
# Paths do not cross the wire
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class _Holder:
    payload: Any


@pytest.fixture
def a_file(tmp_path):
    f = tmp_path / "data.txt"
    f.write_text("client bytes")
    return f


def test_save_value_rejects_a_bare_path(remote, server_cache, a_file):
    """A Path would arrive as a bare string the server resolves itself."""
    with pytest.raises(RemotePathUnsupported) as excinfo:
        remote.save_value(a_file)
    assert str(a_file) in str(excinfo.value)
    # Refused before the RPC: nothing reached the server.
    assert not server_cache.values.storage


@pytest.mark.parametrize(
    "wrap",
    [
        pytest.param(lambda p: [1, p], id="list"),
        pytest.param(lambda p: (p,), id="tuple"),
        pytest.param(lambda p: {"a": {"b": p}}, id="nested-dict"),
        pytest.param(lambda p: _Holder(payload=[p]), id="dataclass"),
    ],
)
def test_save_value_rejects_a_nested_path(remote, server_cache, a_file, wrap):
    """Destructuring walks into containers, so the guard has to as well."""
    with pytest.raises(RemotePathUnsupported):
        remote.save_value(wrap(a_file))
    assert not server_cache.values.storage


def test_save_value_still_accepts_the_bytes_escape_hatch(remote, a_file):
    """Returning ``bytes`` is the documented way to ship content remotely."""
    key = remote.save_value(a_file.read_bytes())
    assert remote.load_value(key) == b"client bytes"


def test_rejection_is_a_save_error(a_file):
    """``SaveError`` is what the two-phase save protocol degrades on."""
    assert issubclass(RemotePathUnsupported, SaveError)


def test_prepare_degrades_a_path_argument_to_a_digest_only_reference(remote, a_file):
    """The sealed key must still be the one a later lookup computes.

    This is the regression the guard buys: letting the path through made the
    server digest *its* view of that name, so the record was filed under a
    key no client could reproduce.
    """
    call = Call(name="f", arguments={"p": a_file, "n": 3})
    prepared = remote.prepare(call)
    assert prepared.key == call.to_lookup_key()
    # The argument survives as its (locally computed) digest, not as content.
    assert prepared.digested.arguments["p"] == digest(a_file)


def test_saving_a_live_call_carrying_a_path_is_rejected(remote, server_cache, a_file):
    """The one-shot form ships values too — the server would stash them."""
    with pytest.raises(Rejected):
        remote.save(Call(name="f", arguments={"p": a_file}, result=1))
    with pytest.raises(Rejected):
        remote.save(Call(name="f", arguments={"x": 1}, result=[a_file]))
    assert not server_cache.calls.storage


def test_load_value_refuses_a_path_materialized_on_the_server(
    remote, server_cache, a_file
):
    """A path stored remotely comes back pointing into the server's temp dir.

    Materialization happens on the server's filesystem and only the *name*
    travels back, so the client would be handed a dangling reference — one
    the server unlinks as soon as its own reference dies.
    """
    key = server_cache.save_value(a_file)  # stored server-side, by content
    with pytest.raises(RemotePathUnsupported) as excinfo:
        remote.load_value(key)
    assert key in str(excinfo.value)


def test_load_value_refuses_a_path_nested_in_a_container(
    remote, server_cache, a_file
):
    key = server_cache.save_value({"out": [a_file]})
    with pytest.raises(RemotePathUnsupported):
        remote.load_value(key)


def test_lazy_call_only_trips_on_the_path_value(remote, server_cache, a_file):
    """Records stay queryable; only touching the path value fails."""
    key = server_cache.save(Call(name="f", arguments={"x": 1}, result=a_file))
    lc = remote.load(key)
    assert dict(lc.arguments) == {"x": 1}
    with pytest.raises(RemotePathUnsupported):
        lc.result
