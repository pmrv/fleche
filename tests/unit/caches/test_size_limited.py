"""Tests for SizeLimitedCache."""
from fleche.call import Call, QueryCall
from fleche.caches import Cache, SizeLimitedCache
from fleche.storage.memory import ValueMemory, CallMemory

from tests.fixtures import run_workers


def make_slcache(max_size: int) -> SizeLimitedCache:
    return SizeLimitedCache(values=ValueMemory({}), calls=CallMemory({}), max_size=max_size)


def make_call(name: str, x: int, result: int) -> Call:
    return Call(name=name, arguments={"x": x}, result=result, module="test", version=1, metadata={})


def test_size_limit_enforced():
    """After saving max_size + 1 calls, only max_size remain."""
    cache = make_slcache(max_size=3)

    for i in range(5):
        cache.save(make_call("f", i, i * 2))

    keys = list(cache.calls.list())
    assert len(keys) <= 3


def test_save_and_load():
    """Saved calls can be retrieved when under the size limit."""
    cache = make_slcache(max_size=5)
    c = make_call("f", 42, 84)
    key = cache.save(c)
    loaded = cache.load(key)
    assert loaded.name == "f"
    assert loaded.arguments["x"] == 42
    assert loaded.result == 84


def test_evict_call_only():
    """Eviction removes the call record; values are left in place."""
    cache = make_slcache(max_size=1)

    c1 = make_call("f", 1, 100)
    c2 = make_call("f", 2, 200)
    cache.save(c1)
    cache.save(c2)

    # At most max_size calls remain after automatic eviction
    assert len(list(cache.calls.list())) <= 1


def test_evict_manual():
    """Manual eviction removes the call record."""
    cache = make_slcache(max_size=10)

    c = make_call("f", 7, 77)
    key = cache.save(c)
    assert cache.contains(key)

    cache.evict(key)
    assert not cache.contains(key)



def test_pick_eviction_target_is_overridable():
    """_pick_eviction_target can be overridden to implement deterministic eviction."""

    class FirstEvictionCache(SizeLimitedCache):
        def _pick_eviction_target(self, keys):
            return keys[0]

    cache = FirstEvictionCache(values=ValueMemory({}), calls=CallMemory({}), max_size=2)

    for i in range(4):
        cache.save(make_call("f", i, i))

    remaining = set(str(k) for k in cache.calls.list())
    assert len(remaining) == 2


def test_thread_safety():
    """Concurrent saves do not corrupt the size invariant."""
    cache = make_slcache(max_size=5)

    def save_calls(worker):
        start = worker * 10
        for i in range(start, start + 10):
            cache.save(make_call("f", i, i * 2))

    errors = run_workers(save_calls, 4)

    assert not errors, f"Exceptions during concurrent saves: {errors}"
    keys = list(cache.calls.list())
    assert len(keys) <= 5


def test_query_delegates():
    cache = make_slcache(max_size=5)
    cache.save(make_call("myf", 1, 10))
    cache.save(make_call("myf", 2, 20))
    cache.save(make_call("other", 3, 30))

    tpl = QueryCall(name="myf", arguments=None, metadata=None, module=None, version=None, result=None)
    results = list(cache.query(tpl))
    assert len(results) == 2
    assert all(r.name == "myf" for r in results)


def test_keys_initialized_from_existing_storage():
    """_keys is populated from existing storage on construction; eviction respects pre-existing entries."""
    # Populate a base Cache first, then wrap it with SizeLimitedCache sharing the same storages.
    base = Cache(values=ValueMemory({}), calls=CallMemory({}))
    for i in range(3):
        base.save(make_call("f", i, i))

    # Build a SizeLimitedCache over the same storages with max_size=2.
    # The 3 pre-existing keys must be discovered during __post_init__.
    slc = SizeLimitedCache(values=base.values, calls=base.calls, max_size=2)

    # _keys must reflect all pre-existing entries
    assert len(slc._keys) == 3

    # Saving one more should trigger eviction down to max_size
    slc.save(make_call("f", 99, 99))
    assert len(slc._keys) <= 2
