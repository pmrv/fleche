"""Tests for Cache and CacheStack expand/shrink/evict digest helpers.

These methods reconcile digest-prefix expansion and shrinking across
independent underlying storages (call-store vs. value-store for Cache;
multiple caches for CacheStack).  The logic has several branches
(only-one-side-has-the-key, both-sides-agree, both-sides-disagree,
not-found) that were previously untested.
"""

from unittest.mock import Mock

import pytest

from fleche.call import Call
from fleche.caches import Cache, CacheStack, ReadOnlyCache
from fleche.digest import Digest
from fleche.storage import AmbiguousDigestError, ValueMemory, CallMemory


# ---------------------------------------------------------------------------
# Cache.expand
# ---------------------------------------------------------------------------

def test_cache_expand_unknown_key_raises_keyerror():
    cache = Cache(ValueMemory({}), CallMemory({}))
    with pytest.raises(KeyError):
        cache.expand("deadbeef")


def test_cache_expand_short_prefix_returns_full_digest():
    cache = Cache(ValueMemory({}), CallMemory({}))
    call = Call(name="f", arguments={"a": 1}, result="ok", module="m", version="1.0", metadata={})
    full = cache.save(call)

    assert cache.expand(full[:6]) == full


def test_cache_expand_disagreement_across_calls_and_values_raises():
    """If calls and values each expand the short prefix to a *different*
    full digest, the result is genuinely ambiguous."""
    calls = Mock()
    values = Mock()
    calls.expand.return_value = Digest("a" * 64)
    values.expand.return_value = Digest("b" * 64)
    cache = Cache(values, calls)

    with pytest.raises(AmbiguousDigestError):
        cache.expand("abcd")


# ---------------------------------------------------------------------------
# Cache.shrink
# ---------------------------------------------------------------------------

def test_cache_shrink_unknown_key_raises_keyerror():
    cache = Cache(ValueMemory({}), CallMemory({}))
    with pytest.raises(KeyError):
        cache.shrink("a" * 64)


def test_cache_shrink_dispatches_to_call_storage_when_key_is_a_call():
    """A key that exists in ``calls`` is shrunk against the call keyspace only."""
    calls = Mock()
    values = Mock()
    calls.contains.return_value = True
    calls._shrink.return_value = (Digest("abcd"),)
    cache = Cache(values, calls)

    assert cache.shrink("a" * 64) == "abcd"
    values.contains.assert_not_called()
    values._shrink.assert_not_called()


def test_cache_shrink_dispatches_to_value_storage_when_key_is_a_value():
    """A key that exists only in ``values`` is shrunk against the value keyspace."""
    calls = Mock()
    values = Mock()
    calls.contains.return_value = False
    values.contains.return_value = True
    values._shrink.return_value = (Digest("beef"),)
    cache = Cache(values, calls)

    assert cache.shrink("b" * 64) == "beef"
    calls._shrink.assert_not_called()


def test_cache_shrink_missing_key_raises_keyerror():
    """If neither storage contains the key, ``shrink`` raises ``KeyError``."""
    calls = Mock()
    values = Mock()
    calls.contains.return_value = False
    values.contains.return_value = False
    cache = Cache(values, calls)

    with pytest.raises(KeyError):
        cache.shrink("c" * 64)
    calls._shrink.assert_not_called()
    values._shrink.assert_not_called()


def test_cache_shrink_multiple_keys_returns_tuple_in_order():
    """``shrink(k1, k2, ...)`` returns a tuple in the original order, even
    when keys come from different sub-storages (each sub-storage's batch
    runs once)."""
    c = Cache(ValueMemory({}), CallMemory({}))
    call1 = Call(name="f", arguments={"x": 1}, result="A", module="m", version="1.0", metadata={})
    call2 = Call(name="g", arguments={"y": 2}, result="B", module="m", version="1.0", metadata={})
    k1 = c.save(call1)
    k2 = c.save(call2)

    shrunk = c.shrink(k1, k2)
    assert isinstance(shrunk, tuple)
    assert len(shrunk) == 2
    # Each shrunk prefix expands back to the original key.
    assert c.expand(shrunk[0]) == k1
    assert c.expand(shrunk[1]) == k2


def test_cache_shrink_no_args_raises_typeerror():
    cache = Cache(ValueMemory({}), CallMemory({}))
    with pytest.raises(TypeError):
        cache.shrink()


def test_cache_shrink_batches_per_sub_storage():
    """Each sub-storage receives a single batched call, not one per key."""
    calls = Mock()
    values = Mock()
    calls.contains.return_value = True
    calls._shrink.return_value = (Digest("aaaa"), Digest("bbbb"))
    cache = Cache(values, calls)

    result = cache.shrink("a" * 64, "b" * 64)
    assert result == (Digest("aaaa"), Digest("bbbb"))
    calls._shrink.assert_called_once_with("a" * 64, "b" * 64)
    values._shrink.assert_not_called()


# ---------------------------------------------------------------------------
# CacheStack.evict
# ---------------------------------------------------------------------------

def test_cache_stack_evict_removes_from_all_layers():
    c1 = Cache(ValueMemory({}), CallMemory({}))
    c2 = Cache(ValueMemory({}), CallMemory({}))
    call = Call(name="f", arguments={"a": 1}, result="r", module="m", version="1.0", metadata={})
    c1.save(call)
    c2.save(call)
    key = call.to_lookup_key()
    stack = CacheStack((c1, c2))

    stack.evict(key)

    assert not c1.contains(key)
    assert not c2.contains(key)


# ---------------------------------------------------------------------------
# CacheStack.expand
# ---------------------------------------------------------------------------

def test_cache_stack_expand_unknown_raises_keyerror():
    stack = CacheStack((Cache(ValueMemory({}), CallMemory({})),))
    with pytest.raises(KeyError):
        stack.expand("deadbeef")


def test_cache_stack_expand_finds_full_digest_in_any_layer():
    c1 = Cache(ValueMemory({}), CallMemory({}))
    c2 = Cache(ValueMemory({}), CallMemory({}))
    call = Call(name="f", arguments={"a": 1}, result="r", module="m", version="1.0", metadata={})
    c2.save(call)
    key = call.to_lookup_key()
    stack = CacheStack((c1, c2))

    assert stack.expand(key[:6]) == key


def test_cache_stack_expand_disagreement_across_layers_raises():
    """Two caches expanding a short prefix to different full digests is ambiguous."""
    c1 = Mock()
    c2 = Mock()
    c1.expand.return_value = Digest("abcd" + "0" * 60)
    c2.expand.return_value = Digest("abcd" + "1" * 60)
    stack = CacheStack((c1, c2))

    with pytest.raises(AmbiguousDigestError):
        stack.expand("abcd")


# ---------------------------------------------------------------------------
# CacheStack.shrink
# ---------------------------------------------------------------------------

def test_cache_stack_shrink_unknown_raises_keyerror():
    stack = CacheStack((Cache(ValueMemory({}), CallMemory({})),))
    with pytest.raises(KeyError):
        stack.shrink("a" * 64)


def test_cache_stack_shrink_returns_longest_across_layers():
    """shrink must return the longest (safest) prefix across all layers."""
    c1 = Mock()
    c2 = Mock()
    c1.contains.return_value = True
    c2.contains.return_value = True
    c1._shrink.return_value = (Digest("abcd"),)
    c2._shrink.return_value = (Digest("abcdef"),)
    stack = CacheStack((c1, c2))

    assert stack.shrink("a" * 64) == "abcdef"


def test_cache_stack_shrink_multiple_keys_batches_per_layer():
    """``shrink(k1, k2)`` makes one batched ``_shrink(*present)`` per layer."""
    c1 = Mock()
    c2 = Mock()
    c1.contains.return_value = True
    c2.contains.return_value = True
    c1._shrink.return_value = (Digest("aaaa"), Digest("bbbb"))
    c2._shrink.return_value = (Digest("aaaaaa"), Digest("bbbbbb"))
    stack = CacheStack((c1, c2))

    out = stack.shrink("a" * 64, "b" * 64)
    assert out == (Digest("aaaaaa"), Digest("bbbbbb"))
    c1._shrink.assert_called_once_with("a" * 64, "b" * 64)
    c2._shrink.assert_called_once_with("a" * 64, "b" * 64)


def test_cache_stack_shrink_multiple_keys_skips_layers_without_key():
    """Layers that don't contain a key are not asked to shrink it."""
    c1 = Mock()
    c2 = Mock()
    # c1 has k1 only; c2 has k2 only.
    c1.contains.side_effect = lambda k: k == "a" * 64
    c2.contains.side_effect = lambda k: k == "b" * 64
    c1._shrink.return_value = (Digest("aaaa"),)
    c2._shrink.return_value = (Digest("bbbb"),)
    stack = CacheStack((c1, c2))

    out = stack.shrink("a" * 64, "b" * 64)
    assert out == (Digest("aaaa"), Digest("bbbb"))
    c1._shrink.assert_called_once_with("a" * 64)
    c2._shrink.assert_called_once_with("b" * 64)


# ---------------------------------------------------------------------------
# CacheWrapper._shrink (ReadOnlyCache as a representative concrete subclass)
# ---------------------------------------------------------------------------

def _make_call(name: str, x: int) -> Call:
    return Call(name=name, arguments={"x": x}, result="r", module="m", version="1.0", metadata={})


def test_cache_wrapper_shrink_single_key_returns_digest_not_nested_tuple():
    """CacheWrapper._shrink with one key must return a flat Digest, not a nested tuple.

    ty flags ``(r,)`` as potentially creating ``tuple[tuple[Digest, ...]]``
    when ``self.cache.shrink(*keys)`` is inferred as returning
    ``tuple[Digest, ...]``.  At runtime BaseCache.shrink returns a bare
    Digest for one key, so the wrap is correct — this test pins that.
    """
    inner = Cache(ValueMemory({}), CallMemory({}))
    key = inner.save(_make_call("f", 1))
    wrapper = ReadOnlyCache(inner)

    short = wrapper.shrink(key)

    assert isinstance(short, Digest), f"expected Digest, got {type(short)}: {short!r}"
    assert not isinstance(short, tuple), "shrink(single_key) must not return a nested tuple"
    assert inner.expand(short) == key


def test_cache_wrapper_shrink_multiple_keys_returns_flat_tuple_of_digests():
    """CacheWrapper._shrink with multiple keys must return a flat tuple[Digest, ...],
    not tuple[tuple[Digest, ...]] (which would happen if the wrapping logic were wrong)."""
    inner = Cache(ValueMemory({}), CallMemory({}))
    k1 = inner.save(_make_call("f", 1))
    k2 = inner.save(_make_call("g", 2))
    wrapper = ReadOnlyCache(inner)

    result = wrapper.shrink(k1, k2)

    assert isinstance(result, tuple)
    assert len(result) == 2
    for element in result:
        assert isinstance(element, Digest), (
            f"expected each element to be a Digest, got {type(element)}: {element!r}"
        )
        assert not isinstance(element, tuple), (
            "shrink result contains a nested tuple — CacheWrapper._shrink wrapping is broken"
        )
    assert inner.expand(result[0]) == k1
    assert inner.expand(result[1]) == k2
