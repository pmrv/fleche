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


def test_cache_activates_cache_built_from_config():
    """A cache built from a config via BaseCache.from_config activates like any other."""
    built = Cache.from_config({"template": "memory"})
    with cache(built):
        assert cache() is built


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


# ---------------------------------------------------------------------------
# _sticky_set / _hard_set primitives (issue #740)
# ---------------------------------------------------------------------------


def test_sticky_set_activates_immediately():
    """_sticky_set(var, value) must set var without entering the with-block."""
    var = _state.ContextVar("test_sticky_set_activates_immediately", default=None)
    _state._sticky_set(var, "value")
    assert var.get() == "value"


def test_sticky_set_returns_sticky_context():
    """_sticky_set must return a _StickyContext usable as a context manager."""
    var = _state.ContextVar("test_sticky_set_returns_sticky_context", default=None)
    cm = _state._sticky_set(var, "value")
    assert isinstance(cm, _state._StickyContext)


def test_sticky_set_with_block_restores_on_exit():
    """with _sticky_set(var, value) must restore the previous value on exit."""
    var = _state.ContextVar("test_sticky_set_with_block_restores_on_exit", default="original")
    with _state._sticky_set(var, "value"):
        assert var.get() == "value"
    assert var.get() == "original"


def test_sticky_set_discard_leaves_value_active():
    """Discarding the returned context manager leaves value active permanently."""
    var = _state.ContextVar("test_sticky_set_discard_leaves_value_active", default="original")
    _state._sticky_set(var, "value")  # discarded
    assert var.get() == "value"


def test_hard_set_activates_every_var_immediately():
    """_hard_set([(var, value), ...]) must set every var before the block starts."""
    var_a = _state.ContextVar("test_hard_set_a", default="a0")
    var_b = _state.ContextVar("test_hard_set_b", default="b0")
    with _state._hard_set([(var_a, "a1"), (var_b, "b1")]):
        assert var_a.get() == "a1"
        assert var_b.get() == "b1"


def test_hard_set_restores_all_on_normal_exit():
    """_hard_set must reset every var to its previous value on exit."""
    var_a = _state.ContextVar("test_hard_set_restores_a", default="a0")
    var_b = _state.ContextVar("test_hard_set_restores_b", default="b0")
    with _state._hard_set([(var_a, "a1"), (var_b, "b1")]):
        pass
    assert var_a.get() == "a0"
    assert var_b.get() == "b0"


def test_hard_set_restores_all_on_exception():
    """_hard_set must reset every var even when the block raises."""
    var_a = _state.ContextVar("test_hard_set_exc_a", default="a0")
    var_b = _state.ContextVar("test_hard_set_exc_b", default="b0")
    with pytest.raises(ValueError):
        with _state._hard_set([(var_a, "a1"), (var_b, "b1")]):
            raise ValueError("boom")
    assert var_a.get() == "a0"
    assert var_b.get() == "b0"


def test_hard_set_resets_in_reverse_order():
    """_hard_set must reset vars in reverse of the order they were set.

    Mirrors BoundWrapper.__call__'s pre-refactor convention (metadata reset before
    cache, i.e. the reverse of the set order) by observing reset order directly
    against a single var re-set twice via two entries.
    """
    var = _state.ContextVar("test_hard_set_reverse_order", default="base")
    var.set("outer")
    with _state._hard_set([(var, "middle"), (var, "inner")]):
        assert var.get() == "inner"
    # after exit, the inner-most set (registered last) is undone first, unwinding
    # back through "middle" to "outer" - net effect is full restoration to "outer".
    assert var.get() == "outer"
