from fleche.call import Call
from fleche.caches import Cache, RefreshingCache
from fleche.storage import ValueMemory, CallMemory


def test_refreshing_cache_always_misses_even_when_underlying_contains_key():
    """A RefreshingCache must always miss on ``load`` and ``contains``.

    Intent: The whole point of :class:`RefreshingCache` is to force re-execution
    by hiding existing entries. Both the ``load`` and ``contains`` overrides
    must return as if the key were absent, regardless of what the wrapped cache
    holds. Saves and value loads must still be forwarded so newly-computed
    results can be stored.
    """
    inner = Cache(ValueMemory({}), CallMemory({}))
    stored = Call(name="f", arguments={"x": 1}, result=2)
    key = inner.save(stored)
    assert inner.contains(key)

    refreshing = RefreshingCache(inner)

    assert refreshing.contains(key) is False, (
        "RefreshingCache.contains must report a miss even when the wrapped "
        "cache holds the key — otherwise nested @fleche calls would short-circuit "
        "during a rerun."
    )

    try:
        refreshing.load(key)
    except KeyError:
        pass
    else:
        raise AssertionError("RefreshingCache.load must raise KeyError on every key")

    fresh = Call(name="f", arguments={"x": 2}, result=3)
    fresh_key = refreshing.save(fresh)
    assert inner.contains(fresh_key), "save must forward to the wrapped cache"
