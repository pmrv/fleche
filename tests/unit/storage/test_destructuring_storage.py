import pytest
from fleche.storage import Memory, DestructuringStorage
from fleche.storage.base import DigestedIterable, DigestedDict, Digested
from fleche.digest import digest, Digest


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


def test_destructuring_storage_recursive_list(ds, mem):
    data = [1, [2, 3], {"a": 4}]
    key = ds.save(data)

    assert key in mem.list()

    loaded = ds.load(key)
    assert loaded == data
    assert isinstance(loaded, list)
    assert isinstance(loaded[1], list)
    assert isinstance(loaded[2], dict)


def test_destructuring_storage_recursive_dict(ds, mem):
    data = {"k1": [1, 2], "k2": {"inner": "v"}}
    key = ds.save(data)

    loaded = ds.load(key)
    assert loaded == data
    assert isinstance(loaded["k1"], list)
    assert isinstance(loaded["k2"], dict)


def test_destructuring_storage_tuple(ds):
    data = (1, 2, (3, 4))
    key = ds.save(data)

    loaded = ds.load(key)
    assert loaded == data
    assert isinstance(loaded, tuple)
    assert isinstance(loaded[2], tuple)


def test_destructuring_storage_evict(ds, mem):
    data = [1, 2]
    key = ds.save(data)
    assert key in mem.list()

    ds.evict(key)
    assert key not in mem.list()
    with pytest.raises(KeyError):
        ds.load(key)


# ---- Tests for _depth ----


@pytest.mark.parametrize("value, expected", [
    (42, 1),
    (3.14, 1),
    ("hello", 1),
    (b"data", 1),
    (True, 1),
    ([1, 2, 3], 2),
    ((1, 2), 2),
    ({"a": 1}, 2),
    ([1, [2, 3]], 3),
    ({"a": {"b": 1}}, 3),
    ([], 1),
    ({}, 1),
    ((), 1),
    ([[[1]]], 4),
    ({"k": [1, [2]]}, 4),
    ({(1, 2): 0}, 3),
])
def test_depth(ds, value, expected):
    assert ds._depth(value) == expected


def test_depth_unknown_type_returns_huge(ds):
    """Non-scalar, non-collection types get depth 2**64 so they always get destructured."""
    assert ds._depth(object()) == 2 ** 64


# ---- Tests for sunder / mend ----


def test_digested_iterable_sunder_list():
    saved = {}
    def save(v):
        d = digest(v)
        saved[d] = v
        return d

    di = DigestedIterable.sunder(save, [10, 20])
    assert isinstance(di, DigestedIterable)
    assert isinstance(di.items, list)
    assert len(di.items) == 2
    assert all(isinstance(i, Digest) for i in di.items)


def test_digested_iterable_sunder_tuple():
    di = DigestedIterable.sunder(lambda v: digest(v), (10, 20))
    assert isinstance(di.items, tuple)


def test_digested_dict_sunder():
    dd = DigestedDict.sunder(lambda v: digest(v), {"a": 1, "b": 2})
    assert isinstance(dd, DigestedDict)
    assert len(dd.items) == 2
    for k, v in dd.items.items():
        assert isinstance(k, Digest)
        assert isinstance(v, Digest)


def test_digested_iterable_mend_roundtrip(ds, mem):
    data = [10, 20, 30]
    key = ds.save(data)
    raw = mem.load(key)
    assert isinstance(raw, DigestedIterable)
    assert raw.mend(ds) == data


def test_digested_dict_mend_roundtrip(ds, mem):
    data = {"x": 1, "y": 2}
    key = ds.save(data)
    raw = mem.load(key)
    assert isinstance(raw, DigestedDict)
    assert raw.mend(ds) == data


def test_digest_transparency():
    """Digested objects must hash identically to the value they replace."""
    data = [1, 2, 3]
    di = DigestedIterable.sunder(digest, data)
    assert digest(di) == digest(data)

    dd_data = {"a": 1}
    dd = DigestedDict.sunder(digest, dd_data)
    assert digest(dd) == digest(dd_data)


# ---- Tests for remaining_depth ----


def test_remaining_depth_0_destructures_everything():
    """With remaining_depth=0, every element gets its own storage slot."""
    mem, ds = make_ds(remaining_depth=0)
    data = [1, 2, 3]
    key = ds.save(data)
    raw = mem.load(key)
    assert isinstance(raw, DigestedIterable)
    assert all(isinstance(i, Digest) for i in raw.items)


def test_remaining_depth_1_inlines_scalars():
    """With remaining_depth=1, scalar elements (depth 1) are kept inline."""
    mem, ds = make_ds(remaining_depth=1)
    data = [1, 2, 3]
    key = ds.save(data)
    raw = mem.load(key)
    assert isinstance(raw, DigestedIterable)
    assert raw.items == [1, 2, 3]
    assert ds.load(key) == data


def test_remaining_depth_1_still_destructures_nested():
    """With remaining_depth=1, nested containers (depth>1) are still destructured."""
    mem, ds = make_ds(remaining_depth=1)
    data = [1, [2, 3]]
    key = ds.save(data)
    raw = mem.load(key)
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


def test_remaining_depth_dict():
    """remaining_depth works for dicts too."""
    mem, ds = make_ds(remaining_depth=1)
    data = {"a": 1, "b": [2, 3]}
    key = ds.save(data)
    raw = mem.load(key)
    assert isinstance(raw, DigestedDict)
    for k, v in raw.items.items():
        if not isinstance(k, Digest):
            assert isinstance(k, str)
    assert ds.load(key) == data


def test_remaining_depth_tuple_preserves_type():
    """Tuples stay tuples through remaining_depth roundtrip."""
    _, ds = make_ds(remaining_depth=1)
    data = (1, 2, (3, 4))
    key = ds.save(data)
    loaded = ds.load(key)
    assert loaded == data
    assert isinstance(loaded, tuple)
    assert isinstance(loaded[2], tuple)


def test_remaining_depth_reduces_storage_slots():
    """Higher remaining_depth should use fewer storage slots."""
    mem0, ds0 = make_ds(remaining_depth=0)
    mem2, ds2 = make_ds(remaining_depth=2)

    data = [1, 2, [3, 4]]
    ds0.save(data)
    ds2.save(data)

    assert len(list(mem2.list())) < len(list(mem0.list()))


def test_load_passthrough_non_digest(ds):
    """_load returns non-Digest values as-is (inline values from mend)."""
    assert ds._load(42) == 42
    assert ds._load("hello") == "hello"
    assert ds._load([1, 2]) == [1, 2]


@pytest.mark.parametrize("data", [[], (), {}])
def test_remaining_depth_empty_containers(data):
    """Empty containers with remaining_depth > 0 round-trip correctly."""
    _, ds = make_ds(remaining_depth=2)
    key = ds.save(data)
    loaded = ds.load(key)
    assert loaded == data
    assert type(loaded) == type(data)
