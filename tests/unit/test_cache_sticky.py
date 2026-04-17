"""Tests for sticky cache() behaviour (issue #104).

cache(new_cache) immediately activates new_cache and returns a context manager
that restores the previous cache on __exit__.  Discarding the context manager
leaves the new cache active.
"""
import pytest

from fleche.caches import Cache, CacheStack
from fleche.state import _CACHE, cache
from fleche.storage import ValueMemory, CallMemory


def _make_cache():
    return Cache(ValueMemory({}), CallMemory({}))


@pytest.fixture(autouse=True)
def restore_cache():
    """Reset the cache ContextVar after every test."""
    token = _CACHE.set(_make_cache())
    yield
    _CACHE.reset(token)


# ---------------------------------------------------------------------------
# Basic sticky behaviour
# ---------------------------------------------------------------------------


def test_cache_call_immediately_sets_cache():
    """cache(c) must activate c without entering a with-block."""
    c = _make_cache()
    cache(c)
    assert cache() is c


def test_cache_call_returns_context_manager():
    """cache(c) must return an object usable as a context manager."""
    c = _make_cache()
    cm = cache(c)
    assert hasattr(cm, "__enter__") and hasattr(cm, "__exit__")


def test_cache_with_block_restores_on_exit():
    """with cache(c) must restore the previous cache after the block."""
    original = cache()
    c = _make_cache()
    with cache(c):
        assert cache() is c
    assert cache() is original


def test_cache_discard_leaves_cache_active():
    """Discarding the context manager leaves the new cache active permanently."""
    c = _make_cache()
    cache(c)  # discard the returned context manager
    assert cache() is c


# ---------------------------------------------------------------------------
# Nesting: the scenario from the issue comment
# ---------------------------------------------------------------------------


def test_nested_sticky_inside_with_block():
    """
    Matches the test case from the issue:

        cache('hdf')
        with cache('memory'):
            cache('void')
        # hdf active again
    """
    hdf = _make_cache()
    memory = _make_cache()
    void = _make_cache()

    cache(hdf)               # sticky set to hdf
    assert cache() is hdf

    with cache(memory):      # sets memory, saves hdf restore point
        assert cache() is memory
        cache(void)          # sticky set to void inside block
        assert cache() is void
                             # __exit__ restores to hdf (ignores void)
    assert cache() is hdf


def test_nested_with_blocks_restore_in_order():
    """Nested with-blocks each restore to their own previous state."""
    outer = _make_cache()
    inner = _make_cache()

    original = cache()
    with cache(outer):
        assert cache() is outer
        with cache(inner):
            assert cache() is inner
        assert cache() is outer
    assert cache() is original


# ---------------------------------------------------------------------------
# stack=True
# ---------------------------------------------------------------------------


def test_stack_immediately_sets_cache_stack():
    """cache(c, stack=True) immediately wraps the current cache in a CacheStack."""
    base = _make_cache()
    layer = _make_cache()
    cache(base)

    cache(layer, stack=True)
    active = cache()
    assert isinstance(active, CacheStack)


def test_stack_with_block_restores():
    """with cache(c, stack=True) restores the pre-stack cache on exit."""
    base = _make_cache()
    layer = _make_cache()
    cache(base)

    with cache(layer, stack=True):
        assert isinstance(cache(), CacheStack)
    assert cache() is base


# ---------------------------------------------------------------------------
# Query (no args) still works
# ---------------------------------------------------------------------------


def test_cache_no_args_returns_current():
    """cache() with no arguments returns the currently active cache."""
    c = _make_cache()
    cache(c)
    assert cache() is c
