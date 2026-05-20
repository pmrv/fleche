from unittest.mock import Mock
import pytest
from fleche.caches import ReadOnlyCache, Rejected


def test_readonly_cache_save():
    from fleche.call import Call

    c = ReadOnlyCache(Mock())
    call = Call(name="test", arguments={"x": 1}, result="result")
    with pytest.raises(Rejected):
        c.save(call)


def test_readonly_cache_evict_rejected():
    """ReadOnlyCache.evict must raise :class:`Rejected` without touching the wrapped cache.

    Contract: "read-only" must extend to deletion as well as writes — otherwise
    a read-only view could still mutate the underlying storage. This test guards
    that invariant and ensures the rejection happens *before* the wrapped cache
    is consulted (no ``evict`` call should reach the inner mock).
    """
    inner = Mock()
    c = ReadOnlyCache(inner)
    with pytest.raises(Rejected):
        c.evict("any-key")
    inner.evict.assert_not_called()


def test_readonlycache_query_forwards_to_wrapped():
    """ReadOnlyCache.query should forward the call to the wrapped cache.

    Intent: Verify that ReadOnlyCache.query delegates to the inner cache and
    yields the same results.
    """
    from fleche.call import Call

    inner = Mock()
    call = Call(
        name="X", arguments={}, metadata={}, module=None, version=None, result=None
    )
    inner.query.return_value = iter([call])

    ro = ReadOnlyCache(inner)
    out = list(
        ro.query(
            Call(
                name=None,
                arguments=None,
                metadata=None,
                module=None,
                version=None,
                result=None,
            )
        )
    )
    assert out == [call], "ReadOnlyCache.query must forward results unchanged"
