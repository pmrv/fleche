"""Tests for the thread-safety mixins (SerializingMixin, PerKeyLockMixin)."""

import threading
from dataclasses import dataclass

import pytest

from fleche.storage import (
    CallMixin,
    CallPickleFile,
    PerKeyLockMixin,
    SerializingMixin,
    ValueMixin,
    ValuePickleFile,
)
from fleche.storage.memory import MemoryBackend
from fleche.storage.pickle_file import PickleFileBackend
from fleche.storage.thread_safe import _PicklableLock, _PicklableRLock


# ---------------------------------------------------------------------------
# Minimal test-local storage classes — no DestructuringMixin, so values are
# stored and loaded as-is (no splitting of collections into sub-entries).
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PlainValueMemory(ValueMixin, MemoryBackend): ...

@dataclass(frozen=True)
class PlainCallMemory(CallMixin, MemoryBackend): ...

@dataclass(frozen=True)
class SerializingValueMemory(SerializingMixin, PlainValueMemory): ...

@dataclass(frozen=True)
class SerializingCallMemory(SerializingMixin, PlainCallMemory): ...

@dataclass(frozen=True)
class PerKeyValueMemory(PerKeyLockMixin, PlainValueMemory):
    # storage: dict makes this unhashable by default; use identity hash so
    # instances can serve as WeakKeyDictionary keys in PerKeyLockMixin.
    __hash__ = object.__hash__

@dataclass(frozen=True)
class PerKeyCallMemory(PerKeyLockMixin, PlainCallMemory):
    __hash__ = object.__hash__

# PickleFile-backed variants exercise a backend where dict-access GIL
# protection does not hide concurrency bugs in the locking code.

@dataclass(frozen=True)
class PlainValuePickle(ValueMixin, PickleFileBackend): ...

@dataclass(frozen=True)
class SerializingValuePickle(SerializingMixin, PlainValuePickle): ...


# ---------------------------------------------------------------------------
# Single-threaded round-trip (value + call, both mixin flavours)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("cls", [SerializingValueMemory, PerKeyValueMemory])
def test_single_threaded_value_roundtrip(cls):
    store = cls(storage={})
    key = store.save([1, 2, 3])
    assert store.load(key) == [1, 2, 3]
    assert store.contains(key)


@pytest.mark.parametrize("cls", [SerializingCallMemory, PerKeyCallMemory])
def test_single_threaded_call_roundtrip(cls):
    from fleche.call import Call

    call = Call(name="f", arguments={"x": 1}, result=None)
    store = cls(storage={})
    key = store.save(call)
    loaded = store.load(key)
    assert loaded.name == "f"
    assert loaded.arguments == {"x": 1}


# ---------------------------------------------------------------------------
# Concurrent access — two backends:
#   1. MemoryBackend (simple, fast)
#   2. PickleFileBackend (file I/O bypasses GIL-protected dict ops)
# ---------------------------------------------------------------------------

def _run_concurrent_save_load(store, n_threads=8, n_writes=50):
    """Save n_threads * n_writes unique scalars from n_threads threads, then verify all round-trip."""
    saved: list[tuple] = []
    lock = threading.Lock()

    def worker(tid):
        local = []
        for i in range(n_writes):
            value = f"t{tid}-i{i}"
            key = store.save(value)
            local.append((key, value))
        with lock:
            saved.extend(local)

    threads = [threading.Thread(target=worker, args=(tid,)) for tid in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(saved) == n_threads * n_writes
    for key, value in saved:
        assert store.load(key) == value


@pytest.mark.parametrize("cls", [SerializingValueMemory, PerKeyValueMemory])
def test_concurrent_saves_memory(cls):
    _run_concurrent_save_load(cls(storage={}))


@pytest.mark.parametrize("cls", [SerializingValuePickle, PlainValuePickle])
def test_concurrent_saves_pickle(tmp_path, cls):
    store = cls.with_pickle(root=tmp_path / cls.__name__)
    _run_concurrent_save_load(store)


def test_value_pickle_file_concurrent_saves(tmp_path):
    """ValuePickleFile is thread-safe via PerKeyLockMixin."""
    store = ValuePickleFile.with_pickle(root=tmp_path / "values")
    _run_concurrent_save_load(store)


@pytest.mark.parametrize("cls", [SerializingValueMemory, PerKeyValueMemory])
def test_concurrent_load_while_writing(cls):
    store = cls(storage={})
    keys = [store.save(i) for i in range(100)]
    errors: list[Exception] = []

    def reader():
        try:
            for k in keys:
                assert store.load(k) in range(100)
        except Exception as e:
            errors.append(e)

    def writer():
        try:
            for i in range(100, 200):
                store.save(i)
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=reader) for _ in range(4)]
    threads += [threading.Thread(target=writer) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors


# ---------------------------------------------------------------------------
# Lock structure
# ---------------------------------------------------------------------------

def test_serializing_uses_single_rlock():
    store = SerializingValueMemory(storage={})
    assert isinstance(store._lock, _PicklableRLock)


def test_per_key_creates_distinct_locks_per_key():
    store = PerKeyValueMemory(storage={})
    lock_a = store._get_key_lock("a")
    lock_b = store._get_key_lock("b")
    assert lock_a is not lock_b
    assert store._get_key_lock("a") is lock_a


def test_per_key_lock_released_when_unused():
    """Locks held by no one should be eligible for GC (WeakValueDictionary)."""
    import gc
    import weakref

    store = PerKeyValueMemory(storage={})
    lock = store._get_key_lock("somekey")
    ref = weakref.ref(lock)
    del lock
    gc.collect()
    # The lock is no longer held by anyone, so it should be collectable.
    assert ref() is None


# ---------------------------------------------------------------------------
# Pickling support (__reduce__ on both picklable lock wrappers)
# ---------------------------------------------------------------------------

def test_picklable_lock_pickle_roundtrip():
    """_PicklableLock.__reduce__ produces a fresh unlocked lock on unpickle."""
    import pickle
    lock = _PicklableLock()
    restored = pickle.loads(pickle.dumps(lock))
    assert isinstance(restored, _PicklableLock)
    # Restored lock must be acquirable (not stuck in acquired state).
    # Use blocking=False so a stuck lock raises AssertionError instead of deadlocking.
    assert restored._lock.acquire(blocking=False), "lock should be free after unpickle"
    restored._lock.release()


def test_picklable_rlock_pickle_roundtrip():
    """_PicklableRLock.__reduce__ produces a fresh unlocked lock on unpickle."""
    import pickle
    lock = _PicklableRLock()
    restored = pickle.loads(pickle.dumps(lock))
    assert isinstance(restored, _PicklableRLock)
    # Use blocking=False so a stuck lock raises AssertionError instead of deadlocking.
    assert restored._lock.acquire(blocking=False), "lock should be free after unpickle"
    restored._lock.release()
