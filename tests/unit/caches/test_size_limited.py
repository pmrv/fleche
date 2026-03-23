"""Tests for SizeLimitedCache."""
import threading

from fleche.call import Call
from fleche.caches import Cache, SizeLimitedCache
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


def test_evict_removes_call():
    """Manual eviction removes the call record; values are left in place."""
    inner = make_cache()
    cache = SizeLimitedCache(cache=inner, max_size=10)

    c = make_call("f", 7, 77)
    key = cache.save(c)

    values_before = set(inner.values.list())
    cache.evict(key)

    # Call should be gone
    assert not cache.contains(key)

    # Values are left in place
    values_after = set(inner.values.list())
    assert values_after == values_before


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
