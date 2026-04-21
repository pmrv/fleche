"""Tests for BoundWrapper: preserving global cache and metadata state.

Covers:
1. Cache state and metadata are preserved when running under a different cache.
2. State is preserved after pickling/unpickling the bound wrapper.
3. Nested functions work: fleche-in-fleche and fleche-in-plain-function.
"""
import pickle
from unittest.mock import MagicMock

import fleche.state as fleche_state
from fleche import fleche
from fleche.caches import Cache
from fleche.state import cache, meta
from fleche.storage import ValueMemory, CallMemory


def _make_cache():
    return Cache(ValueMemory({}), CallMemory({}))


# Module-level fleche functions are required for pickle tests.
@fleche
def _pickle_func(x):
    return x + 1


@fleche
def _pickle_inner(x):
    return x * 2


def _pickle_plain_calls_fleche(x):
    return _pickle_inner(x) + 10


# ---------------------------------------------------------------------------
# 1. Cache state and metadata preserved when running under a different cache
# ---------------------------------------------------------------------------


def test_bound_wrapper_uses_bound_cache_not_outer():
    """BoundWrapper should ignore the outer cache and use the bound one."""
    bound_cache = _make_cache()
    outer_cache = _make_cache()

    @fleche
    def my_func(x):
        return x * 2

    with cache(bound_cache):
        bound = fleche_state.BoundWrapper.bind(my_func)

    with cache(outer_cache):
        result = bound(5)

    assert result == 10
    # Result stored in bound_cache, not in outer_cache
    with cache(bound_cache):
        assert my_func.contains(5)
    with cache(outer_cache):
        assert not my_func.contains(5)


def test_bound_wrapper_preserves_metadata():
    """BoundWrapper should apply the metadata tuple captured at bind time."""
    bound_cache = _make_cache()
    mock_meta = MagicMock()
    mock_meta.name = "test_meta"
    mock_meta.pre.return_value = {}
    mock_meta.post.return_value = {}

    @fleche
    def my_func(x):
        return x + 1

    with cache(bound_cache):
        with meta(mock_meta):
            bound = fleche_state.BoundWrapper.bind(my_func)

    result = bound(3)
    assert result == 4
    mock_meta.pre.assert_called_once()
    mock_meta.post.assert_called_once()


def test_bound_wrapper_ignores_outer_metadata():
    """BoundWrapper should not pick up metadata set after binding."""
    bound_cache = _make_cache()
    bound_mock = MagicMock()
    bound_mock.name = "bound_meta"
    bound_mock.pre.return_value = {}
    bound_mock.post.return_value = {}

    outer_mock = MagicMock()
    outer_mock.name = "outer_meta"
    outer_mock.pre.return_value = {}
    outer_mock.post.return_value = {}

    @fleche
    def my_func(x):
        return x + 1

    with cache(bound_cache):
        with meta(bound_mock):
            bound = fleche_state.BoundWrapper.bind(my_func)

    with meta(outer_mock):
        result = bound(7)

    assert result == 8
    bound_mock.pre.assert_called_once()
    outer_mock.pre.assert_not_called()


# ---------------------------------------------------------------------------
# 2. State preserved after pickling/unpickling
# ---------------------------------------------------------------------------


def test_bound_wrapper_picklable():
    """BoundWrapper roundtrips through pickle and still executes correctly."""
    bound_cache = _make_cache()

    with cache(bound_cache):
        bound = fleche_state.BoundWrapper.bind(_pickle_func)

    restored = pickle.loads(pickle.dumps(bound))
    # Use the live module reference to handle the case where fleche.state was
    # reloaded (by config tests) between the import and this assertion.
    assert isinstance(restored, fleche_state.BoundWrapper)

    result = restored(10)
    assert result == 11
    # Result should be stored in the bound cache that travelled with the wrapper
    with cache(restored.cache):
        assert _pickle_func.contains(10)


def test_bound_wrapper_pickle_preserves_cache_identity():
    """Unpickled BoundWrapper retains the same cache object (by equality)."""
    bound_cache = _make_cache()

    with cache(bound_cache):
        bound = fleche_state.BoundWrapper.bind(_pickle_func)

    restored = pickle.loads(pickle.dumps(bound))
    assert type(restored.cache) is type(bound.cache)


def test_bound_wrapper_pickle_preserves_meta_tuple():
    """Unpickled BoundWrapper retains the same metadata tuple."""
    from fleche.metadata import Tags

    bound_cache = _make_cache()

    with cache(bound_cache):
        with meta(Tags({"env": "test"})):
            bound = fleche_state.BoundWrapper.bind(_pickle_func)

    restored = pickle.loads(pickle.dumps(bound))
    assert restored.meta == bound.meta


# ---------------------------------------------------------------------------
# 3. Nested functions
# ---------------------------------------------------------------------------


def test_bound_wrapper_nested_fleche_functions():
    """BoundWrapper propagates the bound cache to nested fleche calls."""
    bound_cache = _make_cache()
    outer_cache = _make_cache()

    @fleche
    def inner(x):
        return x + 1

    @fleche
    def outer(x):
        return inner(x) * 2

    with cache(bound_cache):
        bound = fleche_state.BoundWrapper.bind(outer)

    with cache(outer_cache):
        result = bound(3)

    assert result == 8  # (3 + 1) * 2

    # Both inner and outer cached in bound_cache
    with cache(bound_cache):
        assert outer.contains(3)
        assert inner.contains(3)

    # Neither cached in outer_cache
    with cache(outer_cache):
        assert not outer.contains(3)
        assert not inner.contains(3)


def test_bound_wrapper_fleche_called_from_plain_function():
    """BoundWrapper propagates bound cache when wrapping a plain function that calls fleche."""
    bound_cache = _make_cache()
    outer_cache = _make_cache()

    @fleche
    def cached_func(x):
        return x * 3

    def plain_func(x):
        return cached_func(x) + 1

    with cache(bound_cache):
        bound = fleche_state.BoundWrapper.bind(plain_func)

    with cache(outer_cache):
        result = bound(2)

    assert result == 7  # 2 * 3 + 1

    # cached_func stored in bound_cache, not outer_cache
    with cache(bound_cache):
        assert cached_func.contains(2)
    with cache(outer_cache):
        assert not cached_func.contains(2)


def test_bound_wrapper_pickle_nested_fleche_in_plain():
    """Pickle roundtrip works for BoundWrapper around a plain function calling fleche."""
    bound_cache = _make_cache()

    with cache(bound_cache):
        bound = fleche_state.BoundWrapper.bind(_pickle_plain_calls_fleche)

    restored = pickle.loads(pickle.dumps(bound))
    result = restored(3)
    assert result == 16  # 3 * 2 + 10

    with cache(restored.cache):
        assert _pickle_inner.contains(3)


# ---------------------------------------------------------------------------
# 4. .fleche namespace proxy
# ---------------------------------------------------------------------------


def test_bound_wrapper_fleche_uses_bound_cache():
    """bound.fleche helpers should activate the bound cache outside any cache context manager."""
    bound_cache = _make_cache()
    outer_cache = _make_cache()

    @fleche
    def my_func(x):
        return x + 1

    with cache(bound_cache):
        bound = fleche_state.BoundWrapper.bind(my_func)
        bound(5)  # populate bound_cache

    # digest is cache-independent; result must match
    assert bound.fleche.digest(5) == my_func.fleche.digest(5)

    # helpers activate the bound cache, not the outer cache
    with cache(outer_cache):
        assert bound.fleche.contains(5)       # bound_cache has the result
        assert not my_func.contains(5)         # outer_cache is empty


def test_bound_wrapper_fleche_raises_for_plain_function():
    """BoundWrapper.fleche raises AttributeError when func is not fleche-decorated."""
    def plain(x):
        return x

    bound_cache = _make_cache()
    with cache(bound_cache):
        bound = fleche_state.BoundWrapper.bind(plain)

    import pytest
    with pytest.raises(AttributeError, match="fleche-decorated"):
        _ = bound.fleche


def test_bound_wrapper_fleche_helpers_have_no_fleche():
    """Helpers exposed via bound.fleche should not recursively expose .fleche."""
    bound_cache = _make_cache()

    @fleche
    def my_func(x):
        return x + 1

    with cache(bound_cache):
        bound = fleche_state.BoundWrapper.bind(my_func)
        bound(5)

    import pytest
    with pytest.raises(AttributeError):
        _ = bound.fleche.contains.fleche
