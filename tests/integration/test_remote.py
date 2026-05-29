"""End-to-end integration tests for :class:`fleche.remote.SshCache`.

These tests bypass SSH entirely: ``python -m fleche remote --serve`` is
launched as a local subprocess so the same stdin/stdout RPC machinery used
in production is exercised in full, including module loading, config file
parsing on the server side, and the ``Popen`` handshake on the client side.
"""

import os
import subprocess
import sys
import textwrap

import pytest

from fleche.call import Call
from fleche.remote import SshCache, _Connection


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
