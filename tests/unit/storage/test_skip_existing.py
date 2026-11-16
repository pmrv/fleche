"""Value storages skip writing a key that is already present.

Values are content-addressed, so re-writing a present key only costs I/O.  The
skip is sound only while ``put`` never publishes a key before its entry is
complete; the crash tests below kill a writer mid-``put`` and check that the
key stays absent, so the next save writes it in full.
"""

import signal
import subprocess
import sys
import textwrap

import pytest

from fleche.digest import Digest, digest
from fleche.storage import ValueMemory

from tests.fixtures import value_storage  # noqa: F401


def _count_puts(storage, monkeypatch):
    calls = []
    original = type(storage).put

    def counting_put(self, value, key):
        calls.append(key)
        return original(self, value, key)

    monkeypatch.setattr(type(storage), "put", counting_put)
    return calls


@pytest.mark.parametrize(
    "value", [42, "text", [1, 2, 3], {"a": [1, 2], "b": (3, 4)}], ids=repr
)
def test_resave_writes_nothing(value_storage, monkeypatch, value):  # noqa: F811
    key = value_storage.save(value)
    puts = _count_puts(value_storage, monkeypatch)
    assert value_storage.save(value) == key
    assert value_storage.save(value, key) == key
    assert puts == []
    assert value_storage.load(key) == value


def test_new_value_is_still_written(value_storage, monkeypatch):  # noqa: F811
    value_storage.save(1)
    puts = _count_puts(value_storage, monkeypatch)
    key = value_storage.save(2)
    assert puts == [key]
    assert value_storage.load(key) == 2


def test_destructured_resave_skips_shared_parts(monkeypatch):
    """A new container re-uses parts already stored and writes only its own entry."""
    storage = ValueMemory({}, remaining_depth=1)
    shared = [1, 2]
    storage.save([shared, [3]])
    puts = _count_puts(storage, monkeypatch)
    storage.save([shared, [4]])
    assert digest(shared) not in puts
    assert digest([4]) in puts


def test_first_save_fixes_the_type():
    """``1`` and ``1.0`` share a digest; the entry already stored is kept."""
    storage = ValueMemory({})
    key = storage.save(1)
    assert storage.save(1.0) == key
    assert type(storage.load(key)) is int


# Run in a child process that is SIGKILLed inside ``_to_file``, so no
# ``finally`` or ``except`` runs — the state a crashed or OOM-killed worker
# leaves behind.  "mid_write" leaves a truncated entry at the path ``put``
# writes to, "after_write" a complete one that ``put`` had not yet published.
_CRASH_SCRIPT = textwrap.dedent(
    """
    import os, signal, sys
    from pathlib import Path
    from fleche.storage import ValuePickleFile, ValueBagOfHoldingH5File

    kind, root, stage, neighbour = sys.argv[1:]
    if kind == "pickle":
        storage = ValuePickleFile.with_pickle(Path(root), secret_key=b"k")
    else:
        storage = ValueBagOfHoldingH5File(
            Path(root), prefix_length=2 if kind == "h5_multi" else 0
        )
    storage.save(neighbour)

    original = type(storage)._to_file

    def dying_to_file(self, value, path):
        if stage == "after_write":
            original(self, value, path)
        elif kind == "h5_multi":
            import h5py
            bag, group = str(path).rsplit("/", 1)
            with h5py.File(bag, "a") as f:
                f.create_group(group).create_dataset("half", data=[1, 2])
        else:
            Path(path).write_bytes(b"\\x80\\x04 truncated")
        os.kill(os.getpid(), signal.SIGKILL)

    type(storage)._to_file = dying_to_file
    storage.save(list(range(10)))
    """
)


def _storage(kind, root):
    if kind == "pickle":
        from fleche.storage import ValuePickleFile

        return ValuePickleFile.with_pickle(root, secret_key=b"k")
    pytest.importorskip("bagofholding")
    from fleche.storage import ValueBagOfHoldingH5File

    return ValueBagOfHoldingH5File(root, prefix_length=2 if kind == "h5_multi" else 0)


def _neighbour_of(key):
    """A string whose digest shares *key*'s two-character prefix, i.e. its multi-bag file."""
    return next(
        f"neighbour{i}" for i in range(100_000) if digest(f"neighbour{i}")[:2] == key[:2]
    )


@pytest.mark.parametrize("stage", ["mid_write", "after_write"])
@pytest.mark.parametrize("kind", ["pickle", "h5", "h5_multi"])
def test_crash_in_put_leaves_key_absent(tmp_path, kind, stage):
    storage = _storage(kind, tmp_path)
    victim = list(range(10))
    key = digest(victim)
    neighbour = _neighbour_of(key)
    proc = subprocess.run(
        [sys.executable, "-c", _CRASH_SCRIPT, kind, str(tmp_path), stage, neighbour],
        capture_output=True,
    )
    assert proc.returncode == -signal.SIGKILL, proc.stderr.decode()

    assert not storage.contains(key)
    assert sorted(storage.list()) == [digest(neighbour)]
    assert storage.load(digest(neighbour)) == neighbour

    # The skip must not mistake the remains for a stored value.
    assert storage.save(victim) == key
    assert storage.load(key) == victim
    if kind == "h5_multi":
        import h5py

        with h5py.File(storage._bag_file(key), "r") as f:
            assert sorted(f) == sorted([key, digest(neighbour)]), "staging leftovers not swept"


def test_multi_bag_overwrite_replaces_entry(tmp_path):
    """``put`` itself still replaces: call storages and ``rebag`` rely on it."""
    pytest.importorskip("bagofholding")
    from fleche.storage.bagofholding_file import BagOfHoldingH5FileBackend

    storage = BagOfHoldingH5FileBackend(tmp_path, prefix_length=2)
    key = Digest("ab" * 32)
    storage.put("old", key)
    storage.put("new", key)
    assert storage.get(key) == "new"
    assert list(storage.list()) == [key]
