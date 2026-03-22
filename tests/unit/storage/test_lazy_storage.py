"""Tests for lazy reconstruction in DestructuringStorage (lazy=True)."""
import pytest
from hypothesis import given, settings, HealthCheck, strategies as st
from fleche.storage import Memory, DestructuringStorage, LazyIterable, LazyDict
from fleche.storage.base import DigestedIterable, DigestedDict

from tests.strategies import st_base_values, st_nested_values, st_key_values


# ---- Fixtures ----


@pytest.fixture
def mem():
    return Memory(storage={})


@pytest.fixture
def lazy_ds(mem):
    return DestructuringStorage(mem, lazy=True)


def make_lazy_ds(remaining_depth=0):
    mem = Memory(storage={})
    ds = DestructuringStorage(mem, remaining_depth=remaining_depth, lazy=True)
    return mem, ds


# ---- LazyIterable ----


def test_lazy_load_list_returns_lazy_iterable(mem, lazy_ds):
    key = lazy_ds.save([1, 2, 3])
    result = lazy_ds.load(key)
    assert isinstance(result, LazyIterable)


def test_lazy_load_tuple_returns_lazy_iterable(mem, lazy_ds):
    key = lazy_ds.save((1, 2, 3))
    result = lazy_ds.load(key)
    assert isinstance(result, LazyIterable)


def test_lazy_iterable_len(lazy_ds):
    key = lazy_ds.save([10, 20, 30])
    result = lazy_ds.load(key)
    assert len(result) == 3


def test_lazy_iterable_getitem(lazy_ds):
    data = [10, 20, 30]
    key = lazy_ds.save(data)
    result = lazy_ds.load(key)
    assert result[0] == 10
    assert result[1] == 20
    assert result[2] == 30


def test_lazy_iterable_negative_index(lazy_ds):
    data = [10, 20, 30]
    key = lazy_ds.save(data)
    result = lazy_ds.load(key)
    assert result[-1] == 30
    assert result[-2] == 20


def test_lazy_iterable_index_out_of_range(lazy_ds):
    key = lazy_ds.save([1, 2])
    result = lazy_ds.load(key)
    with pytest.raises(IndexError):
        result[5]


def test_lazy_iterable_slice(lazy_ds):
    data = [1, 2, 3, 4, 5]
    key = lazy_ds.save(data)
    result = lazy_ds.load(key)
    assert result[1:3] == [2, 3]


def test_lazy_iterable_iter(lazy_ds):
    data = [10, 20, 30]
    key = lazy_ds.save(data)
    result = lazy_ds.load(key)
    assert list(result) == data


def test_lazy_iterable_eq_list(lazy_ds):
    data = [1, 2, 3]
    key = lazy_ds.save(data)
    result = lazy_ds.load(key)
    assert result == data
    assert data == result


def test_lazy_iterable_eq_tuple(lazy_ds):
    data = (1, 2, 3)
    key = lazy_ds.save(data)
    result = lazy_ds.load(key)
    assert result == data
    assert data == result


def test_lazy_iterable_neq_wrong_type(lazy_ds):
    """A LazyIterable wrapping a list should not equal a tuple with same elements."""
    key = lazy_ds.save([1, 2, 3])
    result = lazy_ds.load(key)
    assert result != (1, 2, 3)


def test_lazy_iterable_realize(lazy_ds):
    data = [1, 2, 3]
    key = lazy_ds.save(data)
    result = lazy_ds.load(key)
    assert isinstance(result, LazyIterable)
    realized = result.realize()
    assert realized == data
    assert isinstance(realized, list)


def test_lazy_iterable_realize_tuple(lazy_ds):
    data = (1, 2, 3)
    key = lazy_ds.save(data)
    result = lazy_ds.load(key)
    realized = result.realize()
    assert realized == data
    assert isinstance(realized, tuple)


def test_lazy_iterable_caches_elements(mem, lazy_ds):
    """Each element should be loaded from storage only once."""
    data = [1, 2, 3]
    key = lazy_ds.save(data)
    result = lazy_ds.load(key)

    load_count_before = len(list(mem.list()))
    _ = result[0]
    _ = result[0]  # second access; should use cache
    # No new storage entries created by repeated access
    assert len(list(mem.list())) == load_count_before


def test_lazy_iterable_repr(lazy_ds):
    data = [1, 2]
    key = lazy_ds.save(data)
    result = lazy_ds.load(key)
    assert repr(result) == repr(data)


# ---- LazyDict ----


def test_lazy_load_dict_returns_lazy_dict(mem, lazy_ds):
    key = lazy_ds.save({"a": 1})
    result = lazy_ds.load(key)
    assert isinstance(result, LazyDict)


def test_lazy_dict_len(lazy_ds):
    key = lazy_ds.save({"a": 1, "b": 2})
    result = lazy_ds.load(key)
    assert len(result) == 2


def test_lazy_dict_getitem(lazy_ds):
    data = {"x": 10, "y": 20}
    key = lazy_ds.save(data)
    result = lazy_ds.load(key)
    assert result["x"] == 10
    assert result["y"] == 20


def test_lazy_dict_getitem_missing_key(lazy_ds):
    key = lazy_ds.save({"a": 1})
    result = lazy_ds.load(key)
    with pytest.raises(KeyError):
        result["missing"]


def test_lazy_dict_iter(lazy_ds):
    data = {"a": 1, "b": 2}
    key = lazy_ds.save(data)
    result = lazy_ds.load(key)
    assert set(result) == {"a", "b"}


def test_lazy_dict_keys(lazy_ds):
    data = {"a": 1, "b": 2}
    key = lazy_ds.save(data)
    result = lazy_ds.load(key)
    assert set(result.keys()) == {"a", "b"}


def test_lazy_dict_values(lazy_ds):
    data = {"a": 1, "b": 2}
    key = lazy_ds.save(data)
    result = lazy_ds.load(key)
    assert set(result.values()) == {1, 2}


def test_lazy_dict_items(lazy_ds):
    data = {"a": 1, "b": 2}
    key = lazy_ds.save(data)
    result = lazy_ds.load(key)
    assert dict(result.items()) == data


def test_lazy_dict_contains(lazy_ds):
    data = {"a": 1}
    key = lazy_ds.save(data)
    result = lazy_ds.load(key)
    assert "a" in result
    assert "z" not in result


def test_lazy_dict_eq(lazy_ds):
    data = {"a": 1, "b": 2}
    key = lazy_ds.save(data)
    result = lazy_ds.load(key)
    assert result == data
    assert data == result


def test_lazy_dict_realize(lazy_ds):
    data = {"a": 1, "b": 2}
    key = lazy_ds.save(data)
    result = lazy_ds.load(key)
    realized = result.realize()
    assert realized == data
    assert isinstance(realized, dict)


def test_lazy_dict_repr(lazy_ds):
    data = {"a": 1}
    key = lazy_ds.save(data)
    result = lazy_ds.load(key)
    assert repr(result) == repr(data)


def test_lazy_dict_caches_values(mem, lazy_ds):
    """Each value should be loaded from storage only once."""
    data = {"a": 1}
    key = lazy_ds.save(data)
    result = lazy_ds.load(key)

    storage_count = len(list(mem.list()))
    _ = result["a"]
    _ = result["a"]  # second access; should use cache
    assert len(list(mem.list())) == storage_count


# ---- Roundtrip & correctness ----


@settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(st_nested_values)
def test_lazy_roundtrip_equals_eager(mem, value):
    """Lazy and eager storage produce equal results for all nested values."""
    eager = DestructuringStorage(mem, lazy=False)
    key = eager.save(value)

    lazy = DestructuringStorage(mem, lazy=True)
    loaded = lazy.load(key)

    # Recursively compare: realize any lazy proxies before equality check
    def realize(v):
        if isinstance(v, LazyIterable):
            return type(v._digested.items)(realize(e) for e in v)
        if isinstance(v, LazyDict):
            return {realize(k): realize(val) for k, val in v.items()}
        return v

    assert realize(loaded) == value


@settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(st.lists(st_base_values, min_size=1, max_size=6))
def test_lazy_list_eq_eager_list(mem, items):
    """A lazily loaded list compares equal to the eagerly loaded list."""
    eager_ds = DestructuringStorage(mem)
    lazy_ds = DestructuringStorage(mem, lazy=True)
    key = eager_ds.save(items)
    eager_result = eager_ds.load(key)
    lazy_result = lazy_ds.load(key)
    assert lazy_result == eager_result


@settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(st.dictionaries(st.text(), st_base_values, min_size=1, max_size=6))
def test_lazy_dict_eq_eager_dict(mem, d):
    """A lazily loaded dict compares equal to the eagerly loaded dict."""
    eager_ds = DestructuringStorage(mem)
    lazy_ds = DestructuringStorage(mem, lazy=True)
    key = eager_ds.save(d)
    eager_result = eager_ds.load(key)
    lazy_result = lazy_ds.load(key)
    assert lazy_result == eager_result


def test_lazy_nested_list(lazy_ds):
    """Nested list elements are also lazily loaded."""
    data = [[1, 2], [3, 4]]
    key = lazy_ds.save(data)
    outer = lazy_ds.load(key)
    assert isinstance(outer, LazyIterable)
    inner = outer[0]
    assert isinstance(inner, LazyIterable)
    assert inner[0] == 1
    assert inner[1] == 2


def test_lazy_nested_dict(lazy_ds):
    """Nested dict values are also lazily loaded."""
    data = {"a": {"b": 1}}
    key = lazy_ds.save(data)
    outer = lazy_ds.load(key)
    assert isinstance(outer, LazyDict)
    inner = outer["a"]
    assert isinstance(inner, LazyDict)
    assert inner["b"] == 1


def test_lazy_dict_tuple_keys(lazy_ds):
    """Dict keys that are tuples (stored as DigestedIterable) remain hashable and usable."""
    data = {(1, 2): "a", (3, 4): "b"}
    key = lazy_ds.save(data)
    result = lazy_ds.load(key)
    assert isinstance(result, LazyDict)
    assert result[(1, 2)] == "a"
    assert result[(3, 4)] == "b"
    assert result == data


def test_lazy_false_returns_concrete_types():
    """When lazy=False (default), load returns plain list/dict, not proxies."""
    mem = Memory(storage={})
    ds = DestructuringStorage(mem, lazy=False)
    key = ds.save([1, 2, 3])
    result = ds.load(key)
    assert isinstance(result, list)
    assert not isinstance(result, LazyIterable)


@given(remaining_depth=st.integers(min_value=0, max_value=4))
def test_lazy_remaining_depth_roundtrip(remaining_depth):
    """lazy=True roundtrips all values correctly across different remaining_depth values."""
    mem = Memory(storage={})
    ds = DestructuringStorage(mem, remaining_depth=remaining_depth, lazy=True)
    data = {"a": 1, "b": [2, [3, 4]], "c": (5,)}
    key = ds.save(data)
    loaded = ds.load(key)
    assert loaded == data
