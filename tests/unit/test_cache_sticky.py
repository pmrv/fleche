"""Tests for sticky state-management behaviour (issue #104).

cache(new_cache) / meta(*metadata) immediately activate the new value and return a
context manager that restores the previous value on __exit__.  Discarding the context
manager leaves the new value active (sticky behaviour).
"""
import pytest

import fleche.state as _state
from fleche.caches import Cache, CacheStack
from fleche.metadata import Tags
from fleche.state import cache, meta, tags, project
from fleche.storage import ValueMemory, CallMemory


def _make_cache():
    return Cache(ValueMemory({}), CallMemory({}))


@pytest.fixture(autouse=True)
def restore_cache():
    """Reset the cache ContextVar after every test."""
    token = _state._CACHE.set(_make_cache())
    yield
    _state._CACHE.reset(token)


@pytest.fixture(autouse=True)
def restore_meta():
    """Reset the metadata ContextVar after every test."""
    token = _state._METADATA.set(())
    yield
    _state._METADATA.reset(token)


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


def test_cache_accepts_config_dict():
    """cache(dict) builds an ad-hoc cache via cache_from_config and activates it."""
    with cache({"values": {"type": "memory"}, "calls": {"type": "memory"}}):
        assert isinstance(cache(), Cache)


def test_cache_accepts_template_dict():
    """cache({'template': ...}) expands the template and activates it."""
    with cache({"template": "memory"}):
        active = cache()
        assert isinstance(active, Cache)
        assert isinstance(active.values, ValueMemory)


def test_cache_accepts_config_list_as_stack():
    """cache(list) builds a CacheStack via cache_from_config."""
    with cache([{"template": "memory"}, {"values": {"type": "void"}, "calls": {"type": "void"}}]):
        assert isinstance(cache(), CacheStack)


# ---------------------------------------------------------------------------
# Sticky meta() behaviour
# ---------------------------------------------------------------------------


def test_meta_call_immediately_sets_metadata():
    """meta(m) must activate m without entering a with-block."""
    m = Tags({"key": "value"})
    meta(m)
    assert _state._METADATA.get() == (m,)


def test_meta_call_returns_context_manager():
    """meta(m) must return an object usable as a context manager."""
    m = Tags({"key": "value"})
    cm = meta(m)
    assert hasattr(cm, "__enter__") and hasattr(cm, "__exit__")


def test_meta_with_block_restores_on_exit():
    """with meta(m) must restore the previous metadata after the block."""
    original = _state._METADATA.get()
    m = Tags({"key": "value"})
    with meta(m):
        assert _state._METADATA.get() == (m,)
    assert _state._METADATA.get() == original


def test_meta_discard_leaves_metadata_active():
    """Discarding the context manager leaves the new metadata active permanently."""
    m = Tags({"key": "value"})
    meta(m)  # discard the returned context manager
    assert _state._METADATA.get() == (m,)


def test_meta_stack_immediately_prepends():
    """meta(m, stack=True) immediately prepends m to the current metadata."""
    first = Tags({"a": "1"})
    second = Tags({"b": "2"})
    meta(first)
    meta(second, stack=True)
    assert _state._METADATA.get() == (first, second)


def test_meta_stack_with_block_restores():
    """with meta(m, stack=True) restores the pre-stack metadata on exit."""
    first = Tags({"a": "1"})
    second = Tags({"b": "2"})
    meta(first)
    with meta(second, stack=True):
        assert _state._METADATA.get() == (first, second)
    assert _state._METADATA.get() == (first,)


# ---------------------------------------------------------------------------
# Sticky tags() and project() behaviour
# ---------------------------------------------------------------------------


def test_tags_sticky():
    """tags() must activate immediately without a with-block."""
    tags(user="alice")
    active = _state._METADATA.get()
    assert len(active) == 1
    assert isinstance(active[0], Tags)
    assert active[0].tags["user"] == "alice"


def test_tags_with_block_restores():
    """with tags(...) must restore the previous metadata after the block."""
    original = _state._METADATA.get()
    with tags(user="bob"):
        assert _state._METADATA.get() != original
    assert _state._METADATA.get() == original


def test_project_sticky():
    """project() must activate immediately without a with-block."""
    project("myproject")
    active = _state._METADATA.get()
    assert any(isinstance(m, Tags) and m.tags.get("project") == "myproject" for m in active)


def test_project_with_block_restores():
    """with project(...) must restore the previous metadata after the block."""
    original = _state._METADATA.get()
    with project("temp"):
        assert _state._METADATA.get() != original
    assert _state._METADATA.get() == original
