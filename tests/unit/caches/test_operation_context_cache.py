"""Tests for _operation_context wiring on Cache and BaseCache(OperationContext)."""

import contextlib
import threading
from dataclasses import dataclass

from fleche.call import Call, QueryCall
from fleche.caches import BaseCache, Cache
from fleche.storage.base import Intent, OperationContext
from fleche.storage.memory import ValueMemory, CallMemory
from fleche.storage.thread_safe import PerKeyLockMixin


def make_call(name: str, x: int, result: int) -> Call:
    return Call(name=name, arguments={"x": x}, result=result, module="test", version=1, metadata={})


def make_cache() -> Cache:
    return Cache(values=ValueMemory({}), calls=CallMemory({}))


# ---------------------------------------------------------------------------
# Inheritance checks
# ---------------------------------------------------------------------------

def test_basecache_inherits_operation_context():
    assert issubclass(BaseCache, OperationContext)


def test_cache_inherits_perkey_lock_mixin():
    assert issubclass(Cache, PerKeyLockMixin)


def test_cache_instance_is_operation_context():
    c = make_cache()
    assert isinstance(c, OperationContext)


def test_cache_instance_is_perkey_lock_mixin():
    c = make_cache()
    assert isinstance(c, PerKeyLockMixin)


# ---------------------------------------------------------------------------
# Per-key methods enter _operation_context
# ---------------------------------------------------------------------------

def _make_tracking_cache():
    """Return a Cache subclass that records every (method, key, intent) context entry."""
    entered = []

    class TrackingCache(Cache):
        @contextlib.contextmanager
        def _operation_context(self, key, *, intent=Intent.WRITE):
            entered.append((str(key)[:8], intent))
            with super()._operation_context(key, intent=intent):
                yield

    return TrackingCache(values=ValueMemory({}), calls=CallMemory({})), entered


def test_save_enters_operation_context():
    cache, entered = _make_tracking_cache()
    c = make_call("f", 1, 2)
    cache.save(c)
    assert len(entered) >= 1


def test_load_enters_operation_context():
    cache, entered = _make_tracking_cache()
    c = make_call("f", 1, 2)
    key = cache.save(c)
    entered.clear()
    cache.load(key)
    assert len(entered) >= 1


def test_load_value_enters_operation_context():
    cache, entered = _make_tracking_cache()
    c = make_call("f", 1, 2)
    call_key = cache.save(c)
    # get the value digest for the result (stored separately from call records)
    dc = cache.calls.load(call_key)
    value_key = dc.result
    entered.clear()
    cache.load_value(value_key)
    assert len(entered) >= 1


def test_evict_enters_operation_context():
    cache, entered = _make_tracking_cache()
    c = make_call("f", 1, 2)
    key = cache.save(c)
    entered.clear()
    cache.evict(key)
    assert len(entered) >= 1


def test_contains_enters_operation_context():
    cache, entered = _make_tracking_cache()
    c = make_call("f", 1, 2)
    key = cache.save(c)
    entered.clear()
    cache.contains(key)
    assert len(entered) >= 1


def test_expand_enters_operation_context():
    cache, entered = _make_tracking_cache()
    c = make_call("f", 1, 2)
    key = cache.save(c)
    entered.clear()
    cache.expand(str(key)[:8])
    assert len(entered) >= 1


# ---------------------------------------------------------------------------
# Thread safety: concurrent save/load via per-key locking
# ---------------------------------------------------------------------------

def test_concurrent_saves_are_thread_safe():
    """Multiple threads saving distinct calls must not corrupt the cache."""
    cache = make_cache()
    errors = []
    saved_keys = []
    lock = threading.Lock()

    def worker(tid: int):
        try:
            for i in range(20):
                c = make_call(f"f{tid}", i, tid * 100 + i)
                key = cache.save(c)
                with lock:
                    saved_keys.append(key)
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=worker, args=(tid,)) for tid in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"Exceptions during concurrent saves: {errors}"
    # Every saved key should be loadable
    for key in saved_keys:
        assert cache.contains(key), f"Key {key[:8]}… missing after concurrent saves"


def test_concurrent_save_load_round_trip():
    """Concurrent saves and loads on the same cache produce no data races."""
    cache = make_cache()
    errors = []
    saved: list[tuple] = []
    lock = threading.Lock()

    def saver(tid: int):
        try:
            for i in range(10):
                c = make_call("g", tid * 100 + i, i)
                key = cache.save(c)
                with lock:
                    saved.append((key, i))
        except Exception as e:
            errors.append(e)

    def loader():
        try:
            for _ in range(30):
                with lock:
                    snap = list(saved)
                for key, _ in snap:
                    try:
                        cache.load(key)
                    except KeyError:
                        pass
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=saver, args=(tid,)) for tid in range(4)]
    threads += [threading.Thread(target=loader) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"Exceptions during concurrent save/load: {errors}"


def test_per_key_lock_allows_parallel_ops_on_different_keys():
    """Two threads operating on different keys must not block each other."""
    cache = make_cache()

    # Pre-populate two calls with known keys
    c1 = make_call("h", 1, 10)
    c2 = make_call("h", 2, 20)
    key1 = cache.save(c1)
    key2 = cache.save(c2)

    barrier = threading.Barrier(2)
    results = {}

    def load_key(key, name):
        barrier.wait()  # ensure both start at the same time
        results[name] = cache.load(key).result

    t1 = threading.Thread(target=load_key, args=(key1, "t1"))
    t2 = threading.Thread(target=load_key, args=(key2, "t2"))
    t1.start()
    t2.start()
    t1.join(timeout=5)
    t2.join(timeout=5)

    assert results.get("t1") == 10
    assert results.get("t2") == 20
