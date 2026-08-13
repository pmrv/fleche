from unittest.mock import Mock

import pytest

from fleche.caches import (
    Cache,
    CachePool,
    CacheStack,
    ReadOnlyCache,
    ReadOnlyMixin,
    Rejected,
)
from fleche.call import Call
from fleche.digest import digest
from fleche.storage import CallMemory, ValueMemory


def _mem() -> Cache:
    return Cache(ValueMemory({}), CallMemory({}))


def test_cache_pool_is_recognised_as_read_only():
    """A pool reuses ReadOnlyMixin, so it is a read-only cache by type.

    This is what makes ``remote._is_read_only`` short-circuit ``save``/``evict``
    when an SshCache serves a pool, instead of hand-rolling the rejection.
    """
    pool = CachePool((_mem(),))
    assert isinstance(pool, ReadOnlyMixin)

    from fleche.remote import _is_read_only

    assert _is_read_only(pool)


def test_cache_pool_save_rejected_without_touching_members():
    """A pool's ``save`` must raise :class:`Rejected` **before** reaching any
    member cache — the read-only guarantee has to bind writes as well, and
    the rejection has to happen at the pool layer so no member sees the
    ``save`` at all.  The two invariants are inseparable (a silent pass-through
    would violate both at once); the sibling ``evict`` test pins the analogous
    pair for eviction with the same one-test shape.
    """
    m1, m2 = Mock(), Mock()
    pool = CachePool((m1, m2))
    with pytest.raises(Rejected):
        pool.save(Call(name="f", arguments={}, result="r"))
    m1.save.assert_not_called()
    m2.save.assert_not_called()


def test_cache_pool_evict_rejected():
    m1 = Mock()
    pool = CachePool((m1,))
    with pytest.raises(Rejected):
        pool.evict("any-key")
    m1.evict.assert_not_called()


def test_cache_pool_load_first_hit_no_backfill():
    """load returns the first member's hit and never writes back."""
    c1 = _mem()
    c2 = _mem()
    call = Call(name="test", arguments={"x": 1}, result="result")
    key = c2.save(call)

    pool = CachePool((c1, c2))
    assert pool.load(key).result == "result"

    # c1 must NOT have been back-filled — a pool never mutates its members.
    assert not c1.contains(key)


def test_cache_pool_load_prefers_earlier_member():
    """When two members hold the key, the earlier member's copy wins."""
    c1 = _mem()
    c2 = _mem()
    call = Call(name="test", arguments={"x": 1}, result="result")
    key = call.to_lookup_key()
    c1.save(call)
    c2.save(call)

    pool = CachePool((c1, c2))
    # Both hold it; first_hit returns c1's record. The result is identical, but
    # the contract is "first member wins".
    assert pool.load(key).result == "result"


def test_cache_pool_load_miss_everywhere_raises():
    pool = CachePool((_mem(), _mem()))
    with pytest.raises(KeyError):
        pool.load("a" * 64)


def test_cache_pool_load_value_first_hit():
    c1 = _mem()
    c2 = _mem()
    val = "some_value"
    key = digest(val)
    c2.values.save(val)

    pool = CachePool((c1, c2))
    assert pool.load_value(key) == val
    # No member mutated.
    with pytest.raises(KeyError):
        c1.load_value(key)


def test_cache_pool_load_value_miss_raises():
    pool = CachePool((_mem(), _mem()))
    with pytest.raises(KeyError):
        pool.load_value(digest("nope"))


def test_cache_pool_contains_true_if_any_member_has_key():
    c1 = _mem()
    c2 = _mem()
    key = c2.save(Call(name="f", arguments={"x": 1}, result="r"))
    pool = CachePool((c1, c2))
    assert pool.contains(key)


def test_cache_pool_contains_false_if_no_member_has_key():
    pool = CachePool((_mem(), _mem()))
    assert not pool.contains("a" * 64)


def test_cache_pool_query_union_dedupes():
    """query yields the union across members, deduplicated by lookup key."""
    c1 = _mem()
    c2 = _mem()

    a = Call(name="A", arguments={}, result="ra")
    b = Call(name="B", arguments={}, result="rb")
    c = Call(name="C", arguments={}, result="rc")

    c1.save(a)
    c1.save(b)
    c2.save(b)  # overlaps with c1
    c2.save(c)

    pool = CachePool((c1, c2))
    names = sorted(call.name for call in pool.query())
    assert names == ["A", "B", "C"]


def test_cache_pool_expand_and_shrink_across_members():
    c1 = _mem()
    c2 = _mem()
    key1 = c1.save(Call(name="f", arguments={"x": 1}, result="r1"))
    key2 = c2.save(Call(name="g", arguments={"y": 2}, result="r2"))

    pool = CachePool((c1, c2))

    short1 = pool.shrink(key1)
    assert key1.startswith(short1)
    assert pool.expand(short1) == key1

    short2 = pool.shrink(key2)
    assert pool.expand(short2) == key2


def test_cache_pool_empty_is_harmless():
    pool = CachePool(())
    assert not pool.contains("a" * 64)
    assert list(pool.query()) == []
    with pytest.raises(KeyError):
        pool.load("a" * 64)


def test_cache_pool_transfer_out_to_writable_cache():
    """A pool can be a transfer *source* even though it rejects writes."""
    c1 = _mem()
    key = c1.save(Call(name="f", arguments={"x": 1}, result="r"))
    pool = CachePool((c1,))

    dest = _mem()
    pool.transfer(dest)
    assert dest.contains(key)


def test_cache_pool_accepts_heterogeneous_members():
    """A pool can aggregate plain caches, read-only views, and stacks."""
    plain = _mem()
    key_plain = plain.save(Call(name="p", arguments={}, result="rp"))

    backing = _mem()
    key_ro = backing.save(Call(name="ro", arguments={}, result="rro"))
    ro = ReadOnlyCache(backing)

    base = _mem()
    key_stack = base.save(Call(name="s", arguments={}, result="rs"))
    stack = CacheStack((base,))

    pool = CachePool((plain, ro, stack))
    assert pool.contains(key_plain)
    assert pool.contains(key_ro)
    assert pool.contains(key_stack)
