"""Tests for _operation_context wiring on Cache and BaseCache(OperationContext)."""

import contextlib
import threading

import pytest

from fleche.call import Call
from fleche.caches import BaseCache, Cache
from fleche.storage.base import Intent, OperationContext
from fleche.storage.memory import ValueMemory, CallMemory
from fleche.storage.thread_safe import PerKeyLockMixin


def make_call(name: str, x: int, result: int) -> Call:
    return Call(name=name, arguments={"x": x}, result=result, module="test", version=1, metadata={})


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def tracking_cache():
    """Cache subclass that records every (key_prefix, intent) _operation_context entry."""
    entered = []

    class TrackingCache(Cache):
        @contextlib.contextmanager
        def _operation_context(self, key, *, intent=Intent.WRITE):
            entered.append((str(key)[:8], intent))
            with super()._operation_context(key, intent=intent):
                yield

    return TrackingCache(values=ValueMemory({}), calls=CallMemory({})), entered


# ---------------------------------------------------------------------------
# Inheritance checks
# ---------------------------------------------------------------------------

def test_basecache_inherits_operation_context():
    assert issubclass(BaseCache, OperationContext)


def test_cache_inherits_perkey_lock_mixin():
    assert issubclass(Cache, PerKeyLockMixin)


def test_cache_instance_is_operation_context(clean_cache):
    assert isinstance(clean_cache, OperationContext)


def test_cache_instance_is_perkey_lock_mixin(clean_cache):
    assert isinstance(clean_cache, PerKeyLockMixin)


# ---------------------------------------------------------------------------
# Per-key methods enter _operation_context
# ---------------------------------------------------------------------------

def test_save_enters_operation_context(tracking_cache):
    cache, entered = tracking_cache
    c = make_call("f", 1, 2)
    cache.save(c)
    assert len(entered) >= 1


def test_load_enters_operation_context(tracking_cache):
    cache, entered = tracking_cache
    c = make_call("f", 1, 2)
    key = cache.save(c)
    entered.clear()
    cache.load(key)
    assert len(entered) >= 1


def test_load_value_enters_operation_context(tracking_cache):
    cache, entered = tracking_cache
    c = make_call("f", 1, 2)
    call_key = cache.save(c)
    # get the value digest for the result (stored separately from call records)
    dc = cache.calls.load(call_key)
    value_key = dc.result
    entered.clear()
    cache.load_value(value_key)
    assert len(entered) >= 1


def test_evict_enters_operation_context(tracking_cache):
    cache, entered = tracking_cache
    c = make_call("f", 1, 2)
    key = cache.save(c)
    entered.clear()
    cache.evict(key)
    assert len(entered) >= 1


def test_contains_enters_operation_context(tracking_cache):
    cache, entered = tracking_cache
    c = make_call("f", 1, 2)
    key = cache.save(c)
    entered.clear()
    cache.contains(key)
    assert len(entered) >= 1


def test_expand_enters_operation_context(tracking_cache):
    cache, entered = tracking_cache
    c = make_call("f", 1, 2)
    key = cache.save(c)
    entered.clear()
    cache.expand(str(key)[:8])
    assert len(entered) >= 1


# ---------------------------------------------------------------------------
# Thread safety: concurrent save/load via per-key locking
# ---------------------------------------------------------------------------

def test_concurrent_saves_are_thread_safe(clean_cache):
    """Multiple threads saving distinct calls must not corrupt the cache."""
    errors = []
    saved_keys = []
    lock = threading.Lock()

    def worker(tid: int):
        try:
            for i in range(20):
                c = make_call(f"f{tid}", i, tid * 100 + i)
                key = clean_cache.save(c)
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
        assert clean_cache.contains(key), f"Key {key[:8]}… missing after concurrent saves"


def test_concurrent_save_load_round_trip(clean_cache):
    """Concurrent saves and loads on the same cache produce no data races."""
    errors = []
    saved: list[tuple] = []
    lock = threading.Lock()

    def saver(tid: int):
        try:
            for i in range(10):
                c = make_call("g", tid * 100 + i, i)
                key = clean_cache.save(c)
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
                        clean_cache.load(key)
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
    """Holding one key's lock must not block a concurrent op on a different key.

    A ``HoldingCache`` subclass artificially holds key1's per-key lock until
    signalled.  While that lock is held, a second thread loads key2.  If the
    locks are truly per-key, key2's thread completes immediately; if they
    share a single global lock, key2's thread would be stuck until key1 is
    released (and the ``t2.join(timeout=2)`` assertion would fail).
    """
    t1_holding = threading.Event()
    t1_can_release = threading.Event()
    errors = []
    _key1 = [None]  # mutable cell so the method closure sees the late-bound value

    class HoldingCache(Cache):
        @contextlib.contextmanager
        def _operation_context(self, key, *, intent=Intent.WRITE):
            with super()._operation_context(key, intent=intent):
                # Inside the per-key lock for `key`.  Hold it for key1 only.
                if _key1[0] is not None and str(key) == _key1[0]:
                    t1_holding.set()
                    t1_can_release.wait(timeout=5)
                yield

    cache = HoldingCache(values=ValueMemory({}), calls=CallMemory({}))
    c1 = make_call("h", 1, 10)
    c2 = make_call("h", 2, 20)
    key1 = cache.save(c1)  # _key1[0] is None during setup — no hold
    key2 = cache.save(c2)
    _key1[0] = key1        # arm: subsequent loads of key1 will hold the lock

    def t1_worker():
        try:
            cache.load(key1)
        except Exception as e:
            errors.append(e)

    def t2_worker():
        try:
            cache.load(key2)
        except Exception as e:
            errors.append(e)

    t1 = threading.Thread(target=t1_worker)
    t1.start()
    assert t1_holding.wait(timeout=5), "t1 never acquired key1 lock"

    # While t1 holds key1's lock, t2 should complete key2 without blocking.
    t2 = threading.Thread(target=t2_worker)
    t2.start()
    t2.join(timeout=2)
    assert not t2.is_alive(), "t2 was blocked by t1's key1 lock (per-key locking broken)"

    t1_can_release.set()
    t1.join(timeout=5)
    assert not errors
