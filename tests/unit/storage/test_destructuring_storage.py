import pytest
from dataclasses import dataclass
from hypothesis import given, settings, HealthCheck, strategies as st
from fleche.storage import ValueMixin, DestructuringMixin
from fleche.storage.memory import MemoryBackend
from fleche.storage.base import DigestedIterable, DigestedDict, Digested
from fleche.digest import digest, Digest

from tests.strategies import st_base_values, st_nested_values, st_key_values


@dataclass(frozen=True)
class DestructuringMemory(ValueMixin, DestructuringMixin, MemoryBackend):
    """Test-only class: DestructuringMixin + MemoryBackend wired through ValueMixin."""
    remaining_depth: int = 0


@pytest.fixture
def ds():
    return DestructuringMemory(storage={})


def make_ds(remaining_depth=0):
    return DestructuringMemory(storage={}, remaining_depth=remaining_depth)


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


def test_evict(ds):
    data = [1, 2]
    key = ds.save(data)
    assert key in ds.list()

    ds.evict(key)
    assert key not in ds.list()
    with pytest.raises(KeyError):
        ds.load(key)


# ---- Hash transparency tests (req 1) ----
# Digested classes must hash exactly the way their underlying containers do,
# even when some values have been replaced by Digests.

st_scalars = st.one_of(
    st.integers(), st.floats(allow_nan=False), st.text(), st.binary(), st.booleans(),
)


@pytest.mark.parametrize("container", [list, tuple])
@given(st.lists(st_base_values, min_size=1, max_size=6))
def test_digest_transparency_iterable_all_digests(container, items):
    """DigestedIterable whose items are all Digests hashes like the original container."""
    c = container(items)
    di = DigestedIterable(container(digest(v) for v in items))
    assert digest(di) == digest(c)


@pytest.mark.parametrize("container", [list, tuple])
@given(st.lists(st_base_values, min_size=2, max_size=6))
def test_digest_transparency_iterable_mixed(container, items):
    """DigestedIterable with mixed plain and Digest items still hashes like the original."""
    c = container(items)
    # inline first item, store rest as Digest
    mixed = container([items[0]] + [digest(v) for v in items[1:]])
    di = DigestedIterable(mixed)
    assert digest(di) == digest(c)


@given(st.dictionaries(st_key_values, st_base_values, min_size=1, max_size=6))
def test_digest_transparency_dict_all_digests(d):
    """DigestedDict whose keys and values are all Digests hashes like the original dict."""
    dd = DigestedDict({digest(k): digest(v) for k, v in d.items()})
    assert digest(dd) == digest(d)


@given(st.dictionaries(st_key_values, st_base_values, min_size=2, max_size=6))
def test_digest_transparency_dict_mixed(d):
    """DigestedDict with mixed plain and Digest entries still hashes like the original."""
    items = list(d.items())
    # inline first key-value pair, digest the rest
    mixed = {items[0][0]: items[0][1]}
    mixed.update({digest(k): digest(v) for k, v in items[1:]})
    dd = DigestedDict(mixed)
    assert digest(dd) == digest(d)


# ---- Tests for mend ----


@pytest.mark.parametrize("container", [list, tuple])
@settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(st.lists(st_base_values, min_size=1, max_size=6))
def test_digested_iterable_mend_roundtrip(container, ds, items):
    """DigestedIterable stored by ds can be re-assembled via mend."""
    c = container(items)
    key = ds.save(c)
    # Access the raw stored value directly from the backend dict (bypasses mend)
    raw = ds.storage[key]
    assert isinstance(raw, DigestedIterable)
    assert raw.mend(ds) == c


@settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(st.dictionaries(st.text(), st_base_values, min_size=1, max_size=6))
def test_digested_dict_mend_roundtrip(ds, d):
    """DigestedDict stored by ds can be re-assembled via mend."""
    key = ds.save(d)
    # Access the raw stored value directly from the backend dict (bypasses mend)
    raw = ds.storage[key]
    assert isinstance(raw, DigestedDict)
    assert raw.mend(ds) == d


# ---- Tests for remaining_depth ----


@pytest.mark.parametrize("container", [list, tuple])
@given(st.lists(st_scalars, min_size=1, max_size=6))
def test_remaining_depth_m1_destructures_everything(container, items):
    """With remaining_depth=-1, every element (including scalars) gets its own storage slot."""
    ds = make_ds(remaining_depth=-1)
    key = ds.save(container(items))
    raw = ds.storage[key]
    assert isinstance(raw, DigestedIterable)
    assert all(isinstance(i, Digest) for i in raw.items)


@pytest.mark.parametrize("container", [list, tuple])
@given(st.lists(st_scalars, min_size=1, max_size=6))
def test_remaining_depth_1_inlines_scalars(container, items):
    """With remaining_depth=1, scalar elements are inlined; the container is stored as a plain container (req 3)."""
    ds = make_ds(remaining_depth=1)
    c = container(items)
    key = ds.save(c)
    raw = ds.storage[key]
    # All scalars inlined → no DigestedIterable wrapper, just the plain container
    assert raw == c
    assert type(raw) is container
    assert ds.load(key) == c


@pytest.mark.parametrize("container", [list, tuple])
def test_remaining_depth_1_still_destructures_nested(container):
    """With remaining_depth=1, nested containers (depth > 1) are still stored separately."""
    ds = make_ds(remaining_depth=1)
    data = container([1, [2, 3]])
    key = ds.save(data)
    raw = ds.storage[key]
    assert isinstance(raw, DigestedIterable)
    assert raw.items[0] == 1
    assert isinstance(raw.items[1], Digest)
    assert ds.load(key) == data


@pytest.mark.parametrize("container", [list, tuple])
def test_remaining_depth_2_inlines_flat_list(container):
    """With remaining_depth=2, a flat list (depth 1) inside another list is inlined (req 3)."""
    ds = make_ds(remaining_depth=2)
    data = container([1, [2, 3]])
    key = ds.save(data)
    raw = ds.storage[key]
    # All children inlined → stored as plain container, no DigestedIterable
    assert raw == data
    assert ds.load(key) == data


@pytest.mark.parametrize("container", [list, tuple])
def test_remaining_depth_2_destructures_deeper(container):
    """With remaining_depth=2, a list nested 3 deep is still stored separately."""
    ds = make_ds(remaining_depth=2)
    data = container([1, [[2]]])
    key = ds.save(data)
    raw = ds.storage[key]
    assert isinstance(raw, DigestedIterable)
    assert raw.items[0] == 1
    assert isinstance(raw.items[1], Digest)
    assert ds.load(key) == data


@given(remaining_depth=st.integers(min_value=0, max_value=5))
def test_remaining_depth_roundtrip_nested(remaining_depth):
    """Any remaining_depth correctly roundtrips nested data."""
    ds = make_ds(remaining_depth=remaining_depth)
    data = {"a": 1, "b": [2, [3, 4]], "c": (5,)}
    key = ds.save(data)
    assert ds.load(key) == data


def test_remaining_depth_reduces_storage_slots():
    """Higher remaining_depth should use fewer storage slots."""
    ds0 = make_ds(remaining_depth=0)
    ds2 = make_ds(remaining_depth=2)

    data = [1, 2, [3, 4]]
    ds0.save(data)
    ds2.save(data)

    assert len(list(ds2.list())) < len(list(ds0.list()))


@settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(st_base_values)
def test_load_passthrough_non_digest(ds, value):
    """get returns non-Digest values as-is (inline values from mend)."""
    assert ds.get(value) == value


@given(
    value=st_nested_values,
    write_depth=st.integers(min_value=0, max_value=5),
    read_depth=st.integers(min_value=0, max_value=5),
)
def test_cross_depth_roundtrip(value, write_depth, read_depth):
    """Data written at one remaining_depth is readable at any other."""
    shared = {}
    writer = DestructuringMemory(storage=shared, remaining_depth=write_depth)
    reader = DestructuringMemory(storage=shared, remaining_depth=read_depth)
    key = writer.save(value)
    assert reader.load(key) == value


@pytest.mark.parametrize("data", [[], (), {}])
def test_remaining_depth_empty_containers(data):
    """Empty containers with remaining_depth > 0 round-trip correctly."""
    ds = make_ds(remaining_depth=2)
    key = ds.save(data)
    loaded = ds.load(key)
    assert loaded == data
    assert type(loaded) is type(data)


# ---- Plain-container passthrough (req 3) ----


@pytest.mark.parametrize("container", [list, tuple])
def test_plain_container_stored_when_all_inline(container):
    """When all elements are inlined, the container is stored without a Digested wrapper."""
    ds = make_ds(remaining_depth=10)
    data = container([1, 2, container([3, 4])])
    key = ds.save(data)
    raw = ds.storage[key]
    # Everything fits within remaining_depth → plain container, no DigestedIterable
    assert not isinstance(raw, Digested)
    assert raw == data


def test_plain_dict_stored_when_all_inline():
    """When all dict entries are inlined, the dict is stored without a DigestedDict wrapper."""
    ds = make_ds(remaining_depth=10)
    data = {"a": 1, "b": [2, 3]}
    key = ds.save(data)
    raw = ds.storage[key]
    assert not isinstance(raw, Digested)
    assert raw == data
