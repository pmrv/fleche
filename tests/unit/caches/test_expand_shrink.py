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
from fleche.caches import Cache, CacheStack
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


def test_cache_shrink_returns_longest_of_two_storages():
    """When calls and values disagree on how short they can go, the Cache
    must return the longer (safer) prefix so it remains unambiguous in both."""
    calls = Mock()
    values = Mock()
    calls.shrink.return_value = Digest("abcd")
    values.shrink.return_value = Digest("abcdef")
    cache = Cache(values, calls)

    assert cache.shrink("a" * 64) == "abcdef"


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


def test_cache_stack_evict_tolerates_key_missing_from_some_layers():
    """evict must not fail when the key exists in only some layers."""
    c1 = Cache(ValueMemory({}), CallMemory({}))
    c2 = Cache(ValueMemory({}), CallMemory({}))
    call = Call(name="f", arguments={"a": 1}, result="r", module="m", version="1.0", metadata={})
    c2.save(call)
    key = call.to_lookup_key()
    stack = CacheStack((c1, c2))

    stack.evict(key)  # must not raise

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
    c1.shrink.return_value = Digest("abcd")
    c2.shrink.return_value = Digest("abcdef")
    stack = CacheStack((c1, c2))

    assert stack.shrink("a" * 64) == "abcdef"
