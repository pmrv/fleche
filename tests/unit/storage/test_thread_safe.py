"""Tests for ThreadSafeMixin, MemoryThreadSafe, and ThreadSafeCallStorageAdapter."""

import pickle
import threading
import time

import pytest

from fleche.storage import (
    CallStorageAdapter,
    Memory,
    MemoryThreadSafe,
    ThreadSafeCallStorageAdapter,
    ThreadSafeMixin,
)
from fleche.call import Call
from fleche.digest import Digest


# ---------------------------------------------------------------------------
# ThreadSafeMixin structural tests
# ---------------------------------------------------------------------------


def test_memory_thread_safe_is_mixin_subclass():
    assert issubclass(MemoryThreadSafe, ThreadSafeMixin)
    assert issubclass(MemoryThreadSafe, Memory)


def test_thread_safe_call_storage_adapter_is_mixin_subclass():
    assert issubclass(ThreadSafeCallStorageAdapter, ThreadSafeMixin)
    assert issubclass(ThreadSafeCallStorageAdapter, CallStorageAdapter)


def test_plain_memory_is_not_thread_safe_mixin():
    assert not issubclass(Memory, ThreadSafeMixin)


def test_lock_is_per_instance():
    a = MemoryThreadSafe({})
    b = MemoryThreadSafe({})
    assert a._lock is not b._lock


def test_lock_is_rlock():
    mem = MemoryThreadSafe({})
    assert isinstance(mem._lock, type(threading.RLock()))


def test_lock_identity_stable():
    mem = MemoryThreadSafe({})
    lock1 = mem._lock
    lock2 = mem._lock
    assert lock1 is lock2


# ---------------------------------------------------------------------------
# Pickling
# ---------------------------------------------------------------------------


def _roundtrip(obj):
    return pickle.loads(pickle.dumps(obj))


def test_memory_thread_safe_picklable():
    mem = MemoryThreadSafe({})
    restored = _roundtrip(mem)
    assert isinstance(restored, MemoryThreadSafe)


def test_memory_thread_safe_functional_after_pickle():
    mem = MemoryThreadSafe({})
    key = mem.save(42)
    restored = _roundtrip(mem)
    assert restored.load(key) == 42


def test_thread_safe_call_storage_adapter_picklable():
    adapter = ThreadSafeCallStorageAdapter(MemoryThreadSafe({}))
    restored = _roundtrip(adapter)
    assert isinstance(restored, ThreadSafeCallStorageAdapter)


# ---------------------------------------------------------------------------
# Storage correctness
# ---------------------------------------------------------------------------


def test_memory_thread_safe_save_load_roundtrip():
    mem = MemoryThreadSafe({})
    key = mem.save("hello")
    assert mem.load(key) == "hello"


def test_memory_thread_safe_evict():
    mem = MemoryThreadSafe({})
    key = mem.save("hello")
    assert mem.contains(key)
    mem.evict(key)
    assert not mem.contains(key)


def test_memory_thread_safe_list():
    mem = MemoryThreadSafe({})
    k1 = mem.save(1)
    k2 = mem.save(2)
    assert set(mem.list()) == {k1, k2}


# ---------------------------------------------------------------------------
# Thread-safety: concurrent saves do not cause temporary key absence
# ---------------------------------------------------------------------------


def _make_call(name: str, arg: str) -> Call:
    return Call(
        name=name,
        arguments={"x": arg * 64},
        metadata={},
        module=None,
        version=None,
        result=42,
    )


def test_concurrent_call_saves_no_key_gap():
    """The key must never be absent between evict and re-save under concurrent load."""
    call = _make_call("f", "a")
    key = call.to_lookup_key()

    adapter = ThreadSafeCallStorageAdapter(MemoryThreadSafe({}))
    adapter.save(call)

    errors = []
    gap_detected = threading.Event()

    def saver():
        for _ in range(50):
            adapter.save(call)

    def checker():
        for _ in range(200):
            if not adapter.contains(str(key)):
                gap_detected.set()
                errors.append("key absent during concurrent saves")
            time.sleep(0)

    threads = [threading.Thread(target=saver) for _ in range(4)]
    threads += [threading.Thread(target=checker)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"Detected {len(errors)} gap(s): {errors[0]}"


def test_concurrent_value_saves_no_data_loss():
    """Concurrent saves to MemoryThreadSafe must not lose data."""
    mem = MemoryThreadSafe({})
    n = 100
    keys = []
    lock = threading.Lock()

    def saver(value):
        k = mem.save(value)
        with lock:
            keys.append(k)

    threads = [threading.Thread(target=saver, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(keys) == n
    for k in keys:
        assert mem.contains(k)


# ---------------------------------------------------------------------------
# Cache auto-selects ThreadSafeCallStorageAdapter for MemoryThreadSafe
# ---------------------------------------------------------------------------


def test_cache_uses_thread_safe_adapter_for_memory_thread_safe():
    from fleche.caches import Cache

    mem = MemoryThreadSafe({})
    cache = Cache(mem, mem)
    assert isinstance(cache.calls, ThreadSafeCallStorageAdapter)


def test_cache_uses_plain_adapter_for_plain_memory():
    from fleche.caches import Cache

    mem = Memory({})
    cache = Cache(mem, mem)
    assert isinstance(cache.calls, CallStorageAdapter)
    assert not isinstance(cache.calls, ThreadSafeCallStorageAdapter)
