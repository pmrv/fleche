import pytest
from hypothesis import given, settings, HealthCheck, strategies as st
from fleche.storage import Memory, DestructuringStorage
from fleche.storage.base import DigestedIterable, DigestedDict, Digested
from fleche.digest import digest, Digest

from tests.strategies import st_base_values, st_nested_values, st_key_values


@pytest.fixture
def mem():
    return Memory(storage={})


@pytest.fixture
def ds(mem):
    return DestructuringStorage(mem)


def make_ds(remaining_depth=0):
    mem = Memory(storage={})
    ds = DestructuringStorage(mem, remaining_depth=remaining_depth)
    return mem, ds


# ---- Roundtrip tests ----


@settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(st_nested_values)
def test_roundtrip(ds, value):
    """Any nested value survives a save/load roundtrip."""
    key = ds.save(value)
    assert ds.load(key) == value


@settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(st_nested_values)
def test_save_is_deterministic(ds, value):
    """Saving the same value twice yields the same key."""
    assert ds.save(value) == ds.save(value)


def test_evict(ds, mem):
    data = [1, 2]
    key = ds.save(data)
    assert key in mem.list()

    ds.evict(key)
    assert key not in mem.list()
    with pytest.raises(KeyError):
        ds.load(key)


# ---- Tests for _depth ----

st_scalars = st.one_of(
    st.integers(), st.floats(allow_nan=False), st.text(), st.binary(), st.booleans(),
)


@given(st_scalars)
def test_depth_scalar(value):
    ds = DestructuringStorage(Memory(storage={}))
    assert ds._depth(value) == 0


@given(st.one_of([
    st.lists(st_scalars, min_size=1),
    st.lists(st_scalars, min_size=1).map(tuple),
    st.dictionaries(st.text(), st_scalars, min_size=1),
]))
def test_depth_flat_list(items):
    ds = DestructuringStorage(Memory(storage={}))
    assert ds._depth(items) == 1


# def test_depth_flat_tuple(items):
#     ds = DestructuringStorage(Memory(storage={}))
#     assert ds._depth(items) == 1


# def test_depth_flat_dict(items):
#     ds = DestructuringStorage(Memory(storage={}))
#     assert ds._depth(items) == 1


@pytest.mark.parametrize("value, expected", [
    ([], 1),
    ({}, 1),
    ((), 1),
    ([1, [2, 3]], 2),
    ({"a": {"b": 1}}, 2),
    ([[[1]]], 3),
    ({"k": [1, [2]]}, 3),
    ({(1, 2): 0}, 2),
])
def test_depth_specific(ds, value, expected):
    assert ds._depth(value) == expected


def test_depth_unknown_type_returns_huge(ds):
    """Non-scalar, non-collection types get depth 2**64 so they always get destructured."""
    assert ds._depth(object()) == float('inf')


# ---- Tests for sunder / mend ----


@given(st.lists(st_base_values, min_size=1, max_size=6))
def test_digested_iterable_sunder_list(items):
    di = DigestedIterable.sunder(digest, items)
    assert isinstance(di, DigestedIterable)
    assert isinstance(di.items, list)
    assert len(di.items) == len(items)
    assert all(isinstance(i, Digest) for i in di.items)


@given(st.lists(st_base_values, min_size=1, max_size=6).map(tuple))
def test_digested_iterable_sunder_tuple(items):
    di = DigestedIterable.sunder(digest, items)
    assert isinstance(di.items, tuple)


@given(st.dictionaries(st_key_values, st_base_values, min_size=1, max_size=6))
def test_digested_dict_sunder(d):
    dd = DigestedDict.sunder(digest, d)
    assert isinstance(dd, DigestedDict)
    assert len(dd.items) == len(d)
    for k, v in dd.items.items():
        assert isinstance(k, Digest)
        assert isinstance(v, Digest)


@settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(st.lists(st_base_values, min_size=1, max_size=6))
def test_digested_iterable_mend_roundtrip(ds, mem, items):
    key = ds.save(items)
    raw = mem.load(key)
    assert isinstance(raw, DigestedIterable)
    assert raw.mend(ds) == items


@settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(st.dictionaries(st.text(), st_base_values, min_size=1, max_size=6))
def test_digested_dict_mend_roundtrip(ds, mem, d):
    key = ds.save(d)
    raw = mem.load(key)
    assert isinstance(raw, DigestedDict)
    assert raw.mend(ds) == d


@given(st.lists(st_base_values, min_size=1, max_size=6))
def test_digest_transparency_iterable(items):
    """Digested iterables must hash identically to the value they replace."""
    di = DigestedIterable.sunder(digest, items)
    assert digest(di) == digest(items)


@given(st.dictionaries(st_key_values, st_base_values, min_size=1, max_size=6))
def test_digest_transparency_dict(d):
    """Digested dicts must hash identically to the value they replace."""
    dd = DigestedDict.sunder(digest, d)
    assert digest(dd) == digest(d)


# ---- Tests for remaining_depth ----


@given(st.lists(st_scalars, min_size=1, max_size=6))
def test_remaining_depth_m1_destructures_everything(items):
    """With remaining_depth=-1, every element gets its own storage slot."""
    mem, ds = make_ds(remaining_depth=-1)
    key = ds.save(items)
    raw = mem.load(key)
    assert isinstance(raw, DigestedIterable)
    assert all(isinstance(i, Digest) for i in raw.items)


@given(st.lists(st_scalars, min_size=1, max_size=6))
def test_remaining_depth_1_inlines_scalars(items):
    """With remaining_depth=1, scalar elements (depth 1) are kept inline."""
    mem, ds = make_ds(remaining_depth=1)
    key = ds.save(items)
    raw = mem.load(key)
    assert isinstance(raw, DigestedIterable)
    assert raw.items == items
    assert ds.load(key) == items


def test_remaining_depth_1_still_destructures_nested():
    """With remaining_depth=1, nested containers (depth>1) are still destructured."""
    mem, ds = make_ds(remaining_depth=1)
    data = [1, [2, 3]]
    key = ds.save(data)
    raw = mem.load(key)
    data[6]
    assert isinstance(raw, DigestedIterable)
    assert raw.items[0] == 1
    assert isinstance(raw.items[1], Digest)
    assert ds.load(key) == data


def test_remaining_depth_2_inlines_flat_list():
    """With remaining_depth=2, a flat list (depth 2) inside another list stays inline."""
    mem, ds = make_ds(remaining_depth=2)
    data = [1, [2, 3]]
    key = ds.save(data)
    raw = mem.load(key)
    assert isinstance(raw, DigestedIterable)
    assert raw.items[0] == 1
    assert raw.items[1] == [2, 3]
    assert ds.load(key) == data


def test_remaining_depth_2_destructures_deeper():
    """With remaining_depth=2, a list nested 3 deep is still destructured."""
    mem, ds = make_ds(remaining_depth=2)
    data = [1, [[2]]]
    key = ds.save(data)
    raw = mem.load(key)
    assert isinstance(raw, DigestedIterable)
    assert raw.items[0] == 1
    assert isinstance(raw.items[1], Digest)
    assert ds.load(key) == data


@given(remaining_depth=st.integers(min_value=0, max_value=5))
def test_remaining_depth_roundtrip_nested(remaining_depth):
    """Any remaining_depth correctly roundtrips nested data."""
    mem, ds = make_ds(remaining_depth=remaining_depth)
    data = {"a": 1, "b": [2, [3, 4]], "c": (5,)}
    key = ds.save(data)
    assert ds.load(key) == data


def test_remaining_depth_reduces_storage_slots():
    """Higher remaining_depth should use fewer storage slots."""
    mem0, ds0 = make_ds(remaining_depth=0)
    mem2, ds2 = make_ds(remaining_depth=2)

    data = [1, 2, [3, 4]]
    ds0.save(data)
    ds2.save(data)

    assert len(list(mem2.list())) < len(list(mem0.list()))


@settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(st_base_values)
def test_load_passthrough_non_digest(ds, value):
    """_load returns non-Digest values as-is (inline values from mend)."""
    assert ds._load(value) == value


@given(
    value=st_nested_values,
    write_depth=st.integers(min_value=0, max_value=5),
    read_depth=st.integers(min_value=0, max_value=5),
)
def test_cross_depth_roundtrip(value, write_depth, read_depth):
    """Data written at one remaining_depth is readable at any other."""
    mem = Memory(storage={})
    writer = DestructuringStorage(mem, remaining_depth=write_depth)
    reader = DestructuringStorage(mem, remaining_depth=read_depth)
    key = writer.save(value)
    assert reader.load(key) == value


@pytest.mark.parametrize("data", [[], (), {}])
def test_remaining_depth_empty_containers(data):
    """Empty containers with remaining_depth > 0 round-trip correctly."""
    _, ds = make_ds(remaining_depth=2)
    key = ds.save(data)
    loaded = ds.load(key)
    assert loaded == data
    assert type(loaded) == type(data)
