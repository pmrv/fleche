"""End-to-end integration tests for :class:`fleche.remote.SshCache`.

These tests bypass SSH entirely: ``python -m fleche remote --serve`` is
launched as a local subprocess so the same stdin/stdout RPC machinery used
in production is exercised in full, including module loading, config file
parsing on the server side, and the ``Popen`` handshake on the client side.
"""

import logging
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from fleche import cache, fleche
from fleche.call import Call
from fleche.digest import digest
from fleche.remote import RemotePathUnsupported, SshCache, _Connection


class _LocalSubprocessConnection(_Connection):
    """Launch ``python -m fleche remote --serve`` directly (no SSH)."""

    def __init__(self, cache_name=None, env=None, cwd=None):
        super().__init__()
        self._cache_name = cache_name
        self._env = env
        self._cwd = cwd
        self._proc = None

    def _open(self):
        cmd = [sys.executable, "-m", "fleche", "remote", "--serve"]
        if self._cache_name is not None:
            cmd.extend(["--cache", self._cache_name])
        self._proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=0,
            env=self._env,
            cwd=self._cwd,
        )
        return self._proc.stdin, self._proc.stdout

    def _close(self):
        if self._proc is None:
            return
        proc = self._proc
        self._proc = None
        try:
            if proc.stdin is not None:
                proc.stdin.close()
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=2)


def _build_remote(tmp_path, cache_name=None, toml=None):
    """Construct an :class:`SshCache` that talks to a local subprocess.

    The server subprocess runs with ``cwd=tmp_path`` so its ``./fleche.toml``
    is the test-controlled config — fleche's config loader checks the local
    file first.
    """
    cfg = tmp_path / "fleche.toml"
    cfg.write_text(toml if toml is not None else _DEFAULT_TOML.format(root=tmp_path))
    env = dict(os.environ)
    # Belt-and-braces: also point the XDG fallback away from the user's home.
    env["XDG_CONFIG_HOME"] = str(tmp_path)
    env.pop("HOME", None)
    sc = SshCache(host="ignored")
    object.__setattr__(
        sc,
        "_conn",
        _LocalSubprocessConnection(cache_name=cache_name, env=env, cwd=str(tmp_path)),
    )
    return sc


_DEFAULT_TOML = textwrap.dedent(
    """
    [default]
    cache = "persistent"

    [persistent]
    values.type = "cloudpickle"
    values.root = "{root}/values"
    calls.type = "cloudpickle"
    calls.root = "{root}/calls"
    """
).strip()


def test_subprocess_save_and_load(tmp_path):
    """Save a call via the subprocess, load it back, see the same result."""
    remote_root = tmp_path / "remote"
    remote_root.mkdir()
    sc = _build_remote(remote_root)
    try:
        c = Call(name="example", arguments={"x": 41}, result=42)
        key = sc.save(c)
        assert sc.contains(key)
        lc = sc.load(key)
        assert lc.result == 42
        assert dict(lc.arguments) == {"x": 41}
    finally:
        sc.close()


def test_subprocess_survives_across_two_processes(tmp_path):
    """Data saved through one subprocess must be visible to a fresh one.

    This mirrors the cross-machine use case: machine A saves a result,
    machine B reads it back from the same on-disk cache.
    """
    remote_root = tmp_path / "remote"
    remote_root.mkdir()

    sc1 = _build_remote(remote_root)
    try:
        key = sc1.save(Call(name="shared_fn", arguments={"a": 7}, result="payload"))
    finally:
        sc1.close()

    sc2 = _build_remote(remote_root)
    try:
        assert sc2.contains(key)
        lc = sc2.load(key)
        assert lc.result == "payload"
    finally:
        sc2.close()


def test_subprocess_named_cache(tmp_path):
    """``--cache`` selects a named cache from the remote's config."""
    remote_root = tmp_path / "remote"
    remote_root.mkdir()
    toml = textwrap.dedent(
        f"""
        [default]
        cache = "main"

        [main]
        values.type = "cloudpickle"
        values.root = "{remote_root}/main_values"
        calls.type = "cloudpickle"
        calls.root = "{remote_root}/main_calls"

        [alt]
        values.type = "cloudpickle"
        values.root = "{remote_root}/alt_values"
        calls.type = "cloudpickle"
        calls.root = "{remote_root}/alt_calls"
        """
    ).strip()

    sc_main = _build_remote(remote_root, toml=toml)
    sc_alt = _build_remote(remote_root, toml=toml, cache_name="alt")
    try:
        key = sc_main.save(Call(name="f", arguments={"x": 1}, result=1))
        assert sc_main.contains(key)
        # The alt cache lives at a different root and should be empty.
        assert not sc_alt.contains(key)
    finally:
        sc_main.close()
        sc_alt.close()


# ---------------------------------------------------------------------------
# Paths stop at the SSH boundary
# ---------------------------------------------------------------------------


def test_relative_path_would_resolve_against_the_servers_own_cwd(
    tmp_path, monkeypatch
):
    """The divergence the path guard exists for, reproduced in one process.

    Client and server run in different working directories, so the same
    relative name denotes a *different file* on each side — the single-machine
    stand-in for "the remote is another filesystem".  Only the path string
    crosses the wire, so without the guard the server would digest and store
    its own file under a key the client can never reproduce, and a later load
    would hand back the wrong bytes.
    """
    remote_root = tmp_path / "remote"
    remote_root.mkdir()
    client_root = tmp_path / "client"
    client_root.mkdir()
    (client_root / "data.txt").write_text("client bytes")
    (remote_root / "data.txt").write_text("SERVER BYTES - a different file entirely")
    # The two sides genuinely disagree about what "data.txt" contains.
    assert digest(client_root / "data.txt") != digest(remote_root / "data.txt")

    monkeypatch.chdir(client_root)
    sc = _build_remote(remote_root)
    try:
        with pytest.raises(RemotePathUnsupported):
            sc.save_value(Path("data.txt"))
    finally:
        sc.close()


def test_path_returning_function_runs_uncached_against_a_remote(tmp_path, caplog):
    """A rejected result must not break the call — it just isn't cached.

    ``Rejected`` is the cache's "I won't keep this" signal, which the
    decorator logs and swallows, so the user still gets their file back.
    """
    remote_root = tmp_path / "remote"
    remote_root.mkdir()
    sc = _build_remote(remote_root)
    runs = []

    @fleche
    def produce(name):
        runs.append(name)
        f = tmp_path / f"{name}.txt"
        f.write_text(name)
        return f

    try:
        with cache(sc), caplog.at_level(logging.WARNING):
            assert produce("out").read_text() == "out"
            assert produce("out").read_text() == "out"
    finally:
        sc.close()

    assert runs == ["out", "out"]  # never cached, never wrong
    assert any("rejected save" in r.message.lower() for r in caplog.records)
