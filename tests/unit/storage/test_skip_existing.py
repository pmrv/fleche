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
# leaves behind.  "mid_write" leaves a truncated file at the temp path ``put``
# writes to, "after_write" a complete entry that ``put`` had not yet published.
#
# Multi-bag HDF5 only appears with "after_write": there the bag is closed when
# the kill lands, so it is a real post-crash state.  A kill while H5Bag.save
# holds the bag open leaves HDF5's "open for write" flag set and the whole bag
# unreadable — before staging existed too; staging cannot fix that.  An
# interrupted multi-bag write that closes the bag is covered by
# test_interrupted_multi_bag_write_is_never_published.
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


def _groups(storage, key):
    import h5py

    with h5py.File(storage._bag_file(key), "r") as f:
        return sorted(f)


@pytest.mark.skipif(not hasattr(signal, "SIGKILL"), reason="needs POSIX signals")
@pytest.mark.parametrize(
    "kind, stage",
    [
        ("pickle", "mid_write"),
        ("pickle", "after_write"),
        ("h5", "mid_write"),
        ("h5", "after_write"),
        ("h5_multi", "after_write"),
    ],
)
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


def test_interrupted_multi_bag_write_is_never_published(tmp_path, monkeypatch):
    """An exception inside the real H5Bag.save (Ctrl-C, SIGINT) leaves a partial
    group behind; it must stay a staging group, never one named after the key."""
    pytest.importorskip("bagofholding")
    import h5py

    storage = _storage("h5_multi", tmp_path)
    victim = list(range(10))
    key = digest(victim)
    neighbour = _neighbour_of(key)
    storage.save(neighbour)

    create_dataset = h5py.Group.create_dataset

    def interrupted(self, *args, **kwargs):
        create_dataset(self, *args, **kwargs)
        raise KeyboardInterrupt

    monkeypatch.setattr(h5py.Group, "create_dataset", interrupted)
    with pytest.raises(KeyboardInterrupt):
        storage.save(victim)
    monkeypatch.undo()

    assert any(g.startswith(".staging-") for g in _groups(storage, key))
    assert not storage.contains(key)
    assert sorted(storage.list()) == [digest(neighbour)]
    assert storage.save(victim) == key
    assert storage.load(key) == victim
    assert storage.load(digest(neighbour)) == neighbour


def _leave_staging(storage, key):
    """Plant the staging group a writer of *key* dies with."""
    import h5py
    from fleche.storage.bagofholding_file import _STAGING_PREFIX

    with h5py.File(storage._bag_file(key), "a") as f:
        f.create_group(_STAGING_PREFIX + key).create_dataset("half", data=[1, 2])


def test_put_sweeps_other_writers_staging_leftovers(tmp_path):
    pytest.importorskip("bagofholding")
    from fleche.storage.bagofholding_file import BagOfHoldingH5FileBackend

    storage = BagOfHoldingH5FileBackend(tmp_path, prefix_length=2)
    dead, alive = Digest("ab" + "0" * 62), Digest("ab" + "1" * 62)
    _leave_staging(storage, dead)
    storage.put("x", alive)
    assert _groups(storage, alive) == [alive]


def test_evicting_last_entry_removes_bag_despite_staging_leftover(tmp_path):
    pytest.importorskip("bagofholding")
    from fleche.storage.bagofholding_file import BagOfHoldingH5FileBackend

    storage = BagOfHoldingH5FileBackend(tmp_path, prefix_length=2)
    dead, alive = Digest("ab" + "0" * 62), Digest("ab" + "1" * 62)
    storage.put("x", alive)
    _leave_staging(storage, dead)
    storage.evict(alive)
    assert not storage._bag_file(alive).exists()
    assert not storage._lock_path(alive).exists()


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


# Entries that are present but unreadable — truncated by a power loss (no
# fsync) or an older fleche, signed with a dropped key, damaged on disk — must
# not stay that way just because the key exists: a failed load marks them, and
# the next save rewrites them.


def _tear(storage, key):
    """Replace *key*'s stored entry by garbage, in place."""
    if getattr(storage, "prefix_length", 0):
        import h5py

        with h5py.File(storage._bag_file(key), "a") as f:
            del f[key]
            f.create_group(key).create_dataset("half", data=[1, 2])
    else:
        storage._path(key).write_bytes(b"")


@pytest.mark.parametrize("kind", ["pickle", "h5", "h5_multi"])
def test_unreadable_entry_is_rewritten_after_a_failed_load(tmp_path, kind, monkeypatch):
    storage = _storage(kind, tmp_path)
    value = list(range(10))
    key = storage.save(value)
    _tear(storage, key)
    assert storage.contains(key)
    with pytest.raises(Exception):
        storage.load(key)
    assert storage.save(value) == key
    assert storage.load(key) == value
    # Healed: the skip applies again.
    puts = _count_puts(storage, monkeypatch)
    storage.save(value)
    assert puts == []


def test_unreadable_entry_is_not_rewritten_before_it_is_read(tmp_path, monkeypatch):
    """Healing costs nothing up front: without a failed load the skip stands."""
    storage = _storage("pickle", tmp_path)
    key = storage.save([1, 2, 3])
    _tear(storage, key)
    puts = _count_puts(storage, monkeypatch)
    storage.save([1, 2, 3])
    assert puts == []


def test_failed_load_of_an_absent_key_marks_nothing(tmp_path):
    storage = _storage("pickle", tmp_path)
    key = digest("never stored")
    with pytest.raises(KeyError):
        storage.load(key)
    assert key not in storage._unreadable


def test_entry_signed_with_a_dropped_key_is_rewritten(tmp_path):
    from fleche.storage import ValuePickleFile

    key = ValuePickleFile.with_pickle(tmp_path, secret_key=b"old").save([1, 2, 3])
    storage = ValuePickleFile.with_pickle(tmp_path, secret_key=b"new")
    with pytest.raises(KeyError):
        storage.load(key)
    assert storage.save([1, 2, 3]) == key
    assert storage.load(key) == [1, 2, 3]


def test_cached_function_heals_a_torn_result(tmp_path):
    """End to end: the torn result reads as a miss once, the recompute rewrites it."""
    from fleche import cache, fleche
    from fleche.caches import Cache
    from fleche.storage import CallPickleFile, ValuePickleFile

    values = ValuePickleFile.with_pickle(tmp_path / "v", secret_key=b"k")
    c = Cache(values, CallPickleFile.with_pickle(tmp_path / "c", secret_key=b"k"))
    runs = []

    @fleche()
    def f(x):
        runs.append(x)
        return [x, x + 1]

    with cache(c):
        assert f(1) == [1, 2]
        _tear(values, digest([1, 2]))
        for _ in range(3):
            assert f(1) == [1, 2]
    assert len(runs) == 2
