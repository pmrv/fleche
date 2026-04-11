"""Tests for the thread-safety mixins."""

import threading

import pytest

from fleche.storage import (
    PerKeyCallMemory,
    PerKeyLockMixin,
    PerKeyValueMemory,
    SerializingCallMemory,
    SerializingMixin,
    SerializingValueMemory,
)


@pytest.mark.parametrize(
    "cls", [SerializingValueMemory, PerKeyValueMemory]
)
def test_single_threaded_save_load_roundtrip(cls):
    store = cls(storage={})
    key = store.save([1, 2, 3])
    assert store.load(key) == [1, 2, 3]
    assert store.contains(key)


@pytest.mark.parametrize(
    "cls", [SerializingValueMemory, PerKeyValueMemory]
)
def test_concurrent_saves_all_roundtrip(cls):
    """Hammer the store from many threads and verify every saved value round-trips."""
    store = cls(storage={})
    n_threads = 16
    n_writes = 50

    saved_keys: list[tuple] = []
    saved_lock = threading.Lock()

    def worker(tid):
        # Use unique scalars so the destructuring mixin doesn't dedupe them.
        local = []
        for i in range(n_writes):
            value = f"thread-{tid}-item-{i}"
            key = store.save(value)
            local.append((key, value))
        with saved_lock:
            saved_keys.extend(local)

    threads = [threading.Thread(target=worker, args=(tid,)) for tid in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(saved_keys) == n_threads * n_writes
    # Every key should still be loadable and return its original value.
    for key, value in saved_keys:
        assert store.load(key) == value


@pytest.mark.parametrize(
    "cls", [SerializingValueMemory, PerKeyValueMemory]
)
def test_concurrent_load_while_writing(cls):
    store = cls(storage={})
    keys = [store.save(i) for i in range(100)]

    errors = []

    def reader():
        try:
            for k in keys:
                assert store.load(k) in range(100)
        except Exception as e:  # pragma: no cover - defensive
            errors.append(e)

    def writer():
        try:
            for i in range(100, 200):
                store.save(i)
        except Exception as e:  # pragma: no cover - defensive
            errors.append(e)

    threads = [threading.Thread(target=reader) for _ in range(4)]
    threads += [threading.Thread(target=writer) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors


def test_serializing_uses_single_lock():
    store = SerializingValueMemory(storage={})
    assert isinstance(store._lock, type(threading.RLock()))


def test_per_key_creates_distinct_locks_per_key():
    store = PerKeyValueMemory(storage={})
    lock_a = store._get_key_lock("a")
    lock_b = store._get_key_lock("b")
    assert lock_a is not lock_b
    # Same key returns the same lock.
    assert store._get_key_lock("a") is lock_a


def test_mixin_composition_chains_through_super():
    """A mixin that stacks on top of a thread-safe mixin should still acquire both."""
    entered = []

    class TrackingMixin(SerializingMixin):
        import contextlib as _contextlib

        @_contextlib.contextmanager
        def _operation_context(self, key):
            entered.append(key)
            with super()._operation_context(key):
                yield

    from dataclasses import dataclass
    from fleche.storage import ValueMemory

    @dataclass(frozen=True)
    class Tracked(TrackingMixin, ValueMemory):
        pass

    store = Tracked(storage={})
    k = store.save(42)
    _ = store.load(k)
    # The tracking mixin must have been entered at least once (save) plus once (load).
    assert len(entered) >= 2


def test_frozen_dataclass_semantics_preserved():
    """The mixin classes should remain frozen dataclasses (can't reassign fields)."""
    store = SerializingValueMemory(storage={})
    with pytest.raises((AttributeError, Exception)):
        store.storage = {}  # type: ignore[misc]


def test_serializing_and_per_key_for_call_memory():
    from fleche.call import Call

    call = Call(name="f", arguments={"x": 1}, result=None)

    for cls in (SerializingCallMemory, PerKeyCallMemory):
        store = cls(storage={})
        key = store.save(call)
        loaded = store.load(key)
        assert loaded.name == "f"
        assert loaded.arguments == {"x": 1}
