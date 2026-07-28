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
        assert my_func.fleche.contains(5)
    with cache(outer_cache):
        assert not my_func.fleche.contains(5)


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
    assert isinstance(restored, fleche_state.BoundWrapper)

    result = restored(10)
    assert result == 11
    # Result should be stored in the bound cache that travelled with the wrapper
    with cache(restored.cache):
        assert _pickle_func.fleche.contains(10)


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
        assert outer.fleche.contains(3)
        assert inner.fleche.contains(3)

    # Neither cached in outer_cache
    with cache(outer_cache):
        assert not outer.fleche.contains(3)
        assert not inner.fleche.contains(3)


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
        assert cached_func.fleche.contains(2)
    with cache(outer_cache):
        assert not cached_func.fleche.contains(2)


def test_bound_wrapper_pickle_nested_fleche_in_plain():
    """Pickle roundtrip works for BoundWrapper around a plain function calling fleche."""
    bound_cache = _make_cache()

    with cache(bound_cache):
        bound = fleche_state.BoundWrapper.bind(_pickle_plain_calls_fleche)

    restored = pickle.loads(pickle.dumps(bound))
    result = restored(3)
    assert result == 16  # 3 * 2 + 10

    with cache(restored.cache):
        assert _pickle_inner.fleche.contains(3)


# ---------------------------------------------------------------------------
# 4. .bind helper on wrapped functions
# ---------------------------------------------------------------------------


def test_bind_helper_no_args_returns_bound_wrapper():
    """.fleche.bind() with no args returns a BoundWrapper bound to the current state."""
    bound_cache = _make_cache()

    @fleche
    def my_func(x):
        return x + 1

    with cache(bound_cache):
        bound = my_func.fleche.bind()

    assert isinstance(bound, fleche_state.BoundWrapper)
    assert bound.func is my_func


def test_bind_helper_uses_bound_cache():
    """.fleche.bind() captures the cache active at call time, not at invocation time."""
    bound_cache = _make_cache()
    outer_cache = _make_cache()

    @fleche
    def my_func(x):
        return x * 3

    with cache(bound_cache):
        bound = my_func.fleche.bind()

    with cache(outer_cache):
        result = bound(4)

    assert result == 12
    with cache(bound_cache):
        assert my_func.fleche.contains(4)
    with cache(outer_cache):
        assert not my_func.fleche.contains(4)


def test_bind_helper_partial_args():
    """.fleche.bind(x) pre-applies x so the returned BoundWrapper only needs remaining args."""
    bound_cache = _make_cache()

    @fleche
    def add(a, b):
        return a + b

    with cache(bound_cache):
        bound = add.fleche.bind(10)

    result = bound(5)
    assert result == 15


def test_bind_helper_partial_kwargs():
    """.fleche.bind(b=2) pre-applies a keyword argument."""
    bound_cache = _make_cache()

    @fleche
    def add(a, b):
        return a + b

    with cache(bound_cache):
        bound = add.fleche.bind(b=2)

    result = bound(8)
    assert result == 10


def test_bind_helper_partial_stores_in_bound_cache():
    """Partial .fleche.bind() result stores entries under the bound cache, not the active one."""
    bound_cache = _make_cache()
    outer_cache = _make_cache()

    @fleche
    def add(a, b):
        return a + b

    with cache(bound_cache):
        bound = add.fleche.bind(a=1)

    with cache(outer_cache):
        result = bound(b=9)

    assert result == 10
    with cache(bound_cache):
        assert add.fleche.contains(1, 9)
    with cache(outer_cache):
        assert not add.fleche.contains(1, 9)


def test_bind_helper_accessible_via_fleche_namespace():
    """.fleche.bind is the same object as .bind."""
    @fleche
    def my_func(x):
        return x

    assert my_func.bind is my_func.fleche.bind
