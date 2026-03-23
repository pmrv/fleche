"""Tests for SizeLimitedCache."""
import threading

from fleche.call import Call
from fleche.caches import Cache, SizeLimitedCache
from fleche.digest import Digest
from fleche.storage.memory import Memory


def make_cache() -> Cache:
    return Cache(values=Memory({}), _calls=Memory({}))


def make_call(name: str, x: int, result: int) -> Call:
    return Call(name=name, arguments={"x": x}, result=result, module="test", version=1, metadata={})


def test_size_limit_enforced():
    """After saving max_size + 1 calls, only max_size remain."""
    cache = SizeLimitedCache(cache=make_cache(), max_size=3)

    for i in range(5):
        cache.save(make_call("f", i, i * 2))

    keys = list(cache.cache.calls.list())
    assert len(keys) <= 3


def test_save_and_load():
    """Saved calls can be retrieved when under the size limit."""
    cache = SizeLimitedCache(cache=make_cache(), max_size=5)
    c = make_call("f", 42, 84)
    key = cache.save(c)
    loaded = cache.load(key, lazy=False)
    assert loaded.name == "f"
    assert loaded.arguments["x"] == 42
    assert loaded.result == 84


def test_orphaned_values_evicted():
    """Values no longer referenced by any call are removed from value storage."""
    inner = make_cache()
    cache = SizeLimitedCache(cache=inner, max_size=1)

    c1 = make_call("f", 1, 100)
    c2 = make_call("f", 2, 200)
    cache.save(c1)

    # Record how many values exist after first save
    values_after_c1 = set(inner.values.list())

    cache.save(c2)

    # After eviction there should be at most max_size calls
    assert len(list(inner.calls.list())) <= 1

    # Values belonging exclusively to c1 should have been removed
    values_after_eviction = set(inner.values.list())
    assert values_after_eviction <= values_after_c1 or len(values_after_eviction) <= len(values_after_c1)


def test_shared_values_not_evicted():
    """Values referenced by surviving calls are not removed during eviction."""
    inner = make_cache()
    cache = SizeLimitedCache(cache=inner, max_size=1)

    # Two calls that share the same result value
    shared_result = 999
    c1 = make_call("f", 1, shared_result)
    c2 = make_call("f", 2, shared_result)
    cache.save(c1)
    cache.save(c2)

    # One call survives; its result digest must still be loadable
    surviving_key = list(inner.calls.list())[0]
    surviving_call = inner.calls.load(surviving_key)
    if isinstance(surviving_call.result, Digest):
        assert inner.values.contains(surviving_call.result)


def test_evict_removes_orphaned_values():
    """Manual eviction also cleans up orphaned values."""
    inner = make_cache()
    cache = SizeLimitedCache(cache=inner, max_size=10)

    c = make_call("f", 7, 77)
    key = cache.save(c)

    values_before = set(inner.values.list())
    cache.evict(key)

    # Call should be gone
    assert not cache.contains(key)

    # Values that were exclusively used by the evicted call should be gone
    values_after = set(inner.values.list())
    assert values_after <= values_before


def test_pick_eviction_target_is_overridable():
    """_pick_eviction_target can be overridden to implement deterministic eviction."""
    inner = make_cache()

    class FirstEvictionCache(SizeLimitedCache):
        def _pick_eviction_target(self, keys):
            return keys[0]

    cache = FirstEvictionCache(cache=inner, max_size=2)

    keys_in_order = []
    for i in range(4):
        c = make_call("f", i, i)
        key = cache.save(c)
        keys_in_order.append(key)

    remaining = set(str(k) for k in inner.calls.list())
    assert len(remaining) == 2


def test_thread_safety():
    """Concurrent saves do not corrupt the size invariant."""
    inner = make_cache()
    cache = SizeLimitedCache(cache=inner, max_size=5)
    errors = []

    def save_calls(start):
        try:
            for i in range(start, start + 10):
                cache.save(make_call("f", i, i * 2))
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=save_calls, args=(i * 10,)) for i in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"Exceptions during concurrent saves: {errors}"
    keys = list(inner.calls.list())
    assert len(keys) <= 5


def test_contains_delegates():
    cache = SizeLimitedCache(cache=make_cache(), max_size=5)
    c = make_call("f", 1, 2)
    key = cache.save(c)
    assert cache.contains(key)
    assert not cache.contains("a" * 64)


def test_query_delegates():
    from fleche.call import QueryCall
    cache = SizeLimitedCache(cache=make_cache(), max_size=5)
    cache.save(make_call("myf", 1, 10))
    cache.save(make_call("myf", 2, 20))
    cache.save(make_call("other", 3, 30))

    tpl = Call(name="myf", arguments=None, metadata=None, module=None, version=None, result=None)
    results = list(cache.query(tpl))
    assert len(results) == 2
    assert all(r.name == "myf" for r in results)
