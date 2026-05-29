"""Regression test for issue #592: BaseCache.transfer and QueryIterator.transfer equivalence.

Pins two properties that make it safe to collapse BaseCache.transfer into a
one-line delegator onto QueryIterator.transfer:

1. cache.query() with no template binds ``_cache`` to the source cache on
   every yielded LazyCall, so ``self.evict(key)`` ≡ ``c._cache.evict(key)``.
2. Both surfaces produce identical data decisions (save/skip/evict) across all
   combinations of pop/overwrite/conflict.
"""

import pytest
from fleche.call import Call
from fleche.caches import Cache
from fleche.storage.memory import ValueMemory, CallMemory


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _cache(*calls):
    c = Cache(values=ValueMemory({}), calls=CallMemory({}))
    for call in calls:
        c.save(call)
    return c


_call_a = Call(name="f", arguments={"x": 1}, result=10)
_call_b = Call(name="f", arguments={"x": 2}, result=20)
_call_a_conflict = Call(name="f", arguments={"x": 1}, result=999)  # same key as _call_a


# ---------------------------------------------------------------------------
# 1. _cache identity on wildcard query
# ---------------------------------------------------------------------------

def test_wildcard_query_lazycall_cache_is_source():
    """Every LazyCall from cache.query() has _cache pointing to that cache.

    This is the invariant that makes self.evict(key) == c._cache.evict(key)
    after the refactor.
    """
    src = _cache(_call_a, _call_b)
    for lc in src.query():
        assert lc._cache is src


# ---------------------------------------------------------------------------
# 2. Functional data equivalence: no conflict
# ---------------------------------------------------------------------------

def test_both_surfaces_copy_all_calls_no_conflict():
    """Plain transfer: both surfaces save all source calls in the target."""
    src1, dst1 = _cache(_call_a, _call_b), _cache()
    src2, dst2 = _cache(_call_a, _call_b), _cache()

    src1.transfer(dst1)
    src2.query().transfer(dst2)

    for call in (_call_a, _call_b):
        key = call.to_lookup_key()
        assert dst1.contains(key), "BaseCache.transfer missed a call"
        assert dst2.contains(key), "QueryIterator.transfer missed a call"


def test_both_surfaces_leave_source_intact_without_pop():
    """Without pop=True, source is untouched on both surfaces."""
    src1, dst1 = _cache(_call_a, _call_b), _cache()
    src2, dst2 = _cache(_call_a, _call_b), _cache()

    src1.transfer(dst1, pop=False)
    src2.query().transfer(dst2, pop=False)

    for call in (_call_a, _call_b):
        key = call.to_lookup_key()
        assert src1.contains(key), "BaseCache.transfer: source wrongly evicted"
        assert src2.contains(key), "QueryIterator.transfer: source wrongly evicted"


def test_both_surfaces_evict_source_on_pop():
    """pop=True: both surfaces remove calls from source after transferring."""
    src1, dst1 = _cache(_call_a, _call_b), _cache()
    src2, dst2 = _cache(_call_a, _call_b), _cache()

    src1.transfer(dst1, pop=True)
    src2.query().transfer(dst2, pop=True)

    for call in (_call_a, _call_b):
        key = call.to_lookup_key()
        assert not src1.contains(key), "BaseCache.transfer pop: source still has call"
        assert not src2.contains(key), "QueryIterator.transfer pop: source still has call"
        assert dst1.contains(key)
        assert dst2.contains(key)


# ---------------------------------------------------------------------------
# 3. Functional data equivalence: conflict, overwrite=False (default)
# ---------------------------------------------------------------------------

def test_both_surfaces_skip_save_on_conflict():
    """Conflict + overwrite=False: target entry kept on both surfaces."""
    src1, dst1 = _cache(_call_a), _cache(_call_a_conflict)
    src2, dst2 = _cache(_call_a), _cache(_call_a_conflict)

    src1.transfer(dst1, overwrite=False)
    src2.query().transfer(dst2, overwrite=False)

    # Target retains conflicting value on both surfaces (== _call_a_conflict.result, not _call_a.result)
    assert dst1.load(_call_a.to_lookup_key()).result == _call_a_conflict.result
    assert dst2.load(_call_a.to_lookup_key()).result == _call_a_conflict.result


def test_both_surfaces_skip_source_evict_on_conflict_with_pop():
    """Conflict + pop=True + overwrite=False: source not evicted on both surfaces."""
    src1, dst1 = _cache(_call_a), _cache(_call_a_conflict)
    src2, dst2 = _cache(_call_a), _cache(_call_a_conflict)

    src1.transfer(dst1, pop=True, overwrite=False)
    src2.query().transfer(dst2, pop=True, overwrite=False)

    key = _call_a.to_lookup_key()
    assert src1.contains(key), "BaseCache.transfer: conflict wrongly evicted from source"
    assert src2.contains(key), "QueryIterator.transfer: conflict wrongly evicted from source"


# ---------------------------------------------------------------------------
# 4. Functional data equivalence: conflict, overwrite=True
# ---------------------------------------------------------------------------

def test_both_surfaces_overwrite_target_on_conflict():
    """overwrite=True: both surfaces replace the target entry."""
    src1, dst1 = _cache(_call_a), _cache(_call_a_conflict)
    src2, dst2 = _cache(_call_a), _cache(_call_a_conflict)

    src1.transfer(dst1, overwrite=True)
    src2.query().transfer(dst2, overwrite=True)

    # Source value replaces the conflicting entry (== _call_a.result, not _call_a_conflict.result)
    assert dst1.load(_call_a.to_lookup_key()).result == _call_a.result
    assert dst2.load(_call_a.to_lookup_key()).result == _call_a.result
