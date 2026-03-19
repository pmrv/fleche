import pytest
from fleche.storage import Memory, DestructuringStorage
from fleche.storage.base import DigestedIterable, DigestedDict, Digested
from fleche.digest import digest, Digest


def test_destructuring_storage_recursive_list():
    mem = Memory(storage={})
    ds = DestructuringStorage(mem)

    data = [1, [2, 3], {"a": 4}]
    key = ds.save(data)

    # Check that it's saved in the underlying memory storage
    assert key in mem.list()

    # Check that components are also saved
    # [2, 3] should be saved
    # {"a": 4} should be saved
    # etc.

    loaded = ds.load(key)
    assert loaded == data
    assert isinstance(loaded, list)
    assert isinstance(loaded[1], list)
    assert isinstance(loaded[2], dict)


def test_destructuring_storage_recursive_dict():
    mem = Memory(storage={})
    ds = DestructuringStorage(mem)

    data = {"k1": [1, 2], "k2": {"inner": "v"}}
    key = ds.save(data)

    loaded = ds.load(key)
    assert loaded == data
    assert isinstance(loaded["k1"], list)
    assert isinstance(loaded["k2"], dict)


def test_destructuring_storage_tuple():
    mem = Memory(storage={})
    ds = DestructuringStorage(mem)

    data = (1, 2, (3, 4))
    key = ds.save(data)

    loaded = ds.load(key)
    assert loaded == data
    assert isinstance(loaded, tuple)
    assert isinstance(loaded[2], tuple)


def test_destructuring_storage_evict():
    mem = Memory(storage={})
    ds = DestructuringStorage(mem)

    data = [1, 2]
    key = ds.save(data)
    assert key in mem.list()

    ds.evict(key)
    assert key not in mem.list()
    with pytest.raises(KeyError):
        ds.load(key)


# ---- Tests for _depth ----


class TestDepth:
    def setup_method(self):
        self.ds = DestructuringStorage(Memory(storage={}))

    def test_depth_scalar_int(self):
        assert self.ds._depth(42) == 1

    def test_depth_scalar_float(self):
        assert self.ds._depth(3.14) == 1

    def test_depth_scalar_str(self):
        assert self.ds._depth("hello") == 1

    def test_depth_scalar_bytes(self):
        assert self.ds._depth(b"data") == 1

    def test_depth_scalar_bool(self):
        assert self.ds._depth(True) == 1

    def test_depth_flat_list(self):
        assert self.ds._depth([1, 2, 3]) == 2

    def test_depth_flat_tuple(self):
        assert self.ds._depth((1, 2)) == 2

    def test_depth_flat_dict(self):
        assert self.ds._depth({"a": 1}) == 2

    def test_depth_nested_list(self):
        assert self.ds._depth([1, [2, 3]]) == 3

    def test_depth_nested_dict(self):
        assert self.ds._depth({"a": {"b": 1}}) == 3

    def test_depth_empty_list(self):
        assert self.ds._depth([]) == 1

    def test_depth_empty_dict(self):
        assert self.ds._depth({}) == 1

    def test_depth_empty_tuple(self):
        assert self.ds._depth(()) == 1

    def test_depth_deeply_nested(self):
        assert self.ds._depth([[[1]]]) == 4

    def test_depth_mixed_nesting(self):
        # dict with list value containing nested list
        assert self.ds._depth({"k": [1, [2]]}) == 4

    def test_depth_unknown_type_returns_huge(self):
        """Non-scalar, non-collection types get depth 2**64 so they always get destructured."""
        assert self.ds._depth(object()) == 2 ** 64

    def test_depth_dict_keys_count(self):
        """Dict depth accounts for key depth too."""
        # keys are tuples of depth 2, values are ints of depth 1
        assert self.ds._depth({(1, 2): 0}) == 3


# ---- Tests for sunder / mend ----


class TestSunderMend:
    def test_digested_iterable_sunder_list(self):
        saved = {}
        def save(v):
            d = digest(v)
            saved[d] = v
            return d

        di = DigestedIterable.sunder(save, [10, 20])
        assert isinstance(di, DigestedIterable)
        assert isinstance(di.items, list)
        assert len(di.items) == 2
        # items should be digests, not the original values
        assert all(isinstance(i, Digest) for i in di.items)

    def test_digested_iterable_sunder_tuple(self):
        di = DigestedIterable.sunder(lambda v: digest(v), (10, 20))
        assert isinstance(di.items, tuple)

    def test_digested_dict_sunder(self):
        dd = DigestedDict.sunder(lambda v: digest(v), {"a": 1, "b": 2})
        assert isinstance(dd, DigestedDict)
        assert len(dd.items) == 2
        # keys and values should all be digests
        for k, v in dd.items.items():
            assert isinstance(k, Digest)
            assert isinstance(v, Digest)

    def test_digested_iterable_mend_roundtrip(self):
        mem = Memory(storage={})
        ds = DestructuringStorage(mem)
        data = [10, 20, 30]
        key = ds.save(data)
        # The stored value should be a DigestedIterable
        raw = mem.load(key)
        assert isinstance(raw, DigestedIterable)
        # mend should reconstruct the original
        assert raw.mend(ds) == data

    def test_digested_dict_mend_roundtrip(self):
        mem = Memory(storage={})
        ds = DestructuringStorage(mem)
        data = {"x": 1, "y": 2}
        key = ds.save(data)
        raw = mem.load(key)
        assert isinstance(raw, DigestedDict)
        assert raw.mend(ds) == data

    def test_digest_transparency(self):
        """Digested objects must hash identically to the value they replace."""
        data = [1, 2, 3]
        di = DigestedIterable.sunder(digest, data)
        assert digest(di) == digest(data)

        dd_data = {"a": 1}
        dd = DigestedDict.sunder(digest, dd_data)
        assert digest(dd) == digest(dd_data)


# ---- Tests for remaining_depth > 0 ----


class TestRemainingDepth:
    def test_remaining_depth_0_destructures_everything(self):
        """With remaining_depth=0, every element gets its own storage slot."""
        mem = Memory(storage={})
        ds = DestructuringStorage(mem, remaining_depth=0)
        data = [1, 2, 3]
        key = ds.save(data)
        raw = mem.load(key)
        assert isinstance(raw, DigestedIterable)
        # all items should be Digests (each element stored separately)
        assert all(isinstance(i, Digest) for i in raw.items)

    def test_remaining_depth_1_inlines_scalars(self):
        """With remaining_depth=1, scalar elements (depth 1) are kept inline."""
        mem = Memory(storage={})
        ds = DestructuringStorage(mem, remaining_depth=1)
        data = [1, 2, 3]
        key = ds.save(data)
        raw = mem.load(key)
        assert isinstance(raw, DigestedIterable)
        # scalars have depth 1 <= remaining_depth 1, so they stay as raw values
        assert raw.items == [1, 2, 3]
        # roundtrip still works
        assert ds.load(key) == data

    def test_remaining_depth_1_still_destructures_nested(self):
        """With remaining_depth=1, nested containers (depth>1) are still destructured."""
        mem = Memory(storage={})
        ds = DestructuringStorage(mem, remaining_depth=1)
        data = [1, [2, 3]]
        key = ds.save(data)
        raw = mem.load(key)
        assert isinstance(raw, DigestedIterable)
        # first element (scalar, depth 1) stays inline
        assert raw.items[0] == 1
        # second element ([2,3], depth 2) gets its own digest
        assert isinstance(raw.items[1], Digest)
        assert ds.load(key) == data

    def test_remaining_depth_2_inlines_flat_list(self):
        """With remaining_depth=2, a flat list (depth 2) inside another list stays inline."""
        mem = Memory(storage={})
        ds = DestructuringStorage(mem, remaining_depth=2)
        data = [1, [2, 3]]
        key = ds.save(data)
        raw = mem.load(key)
        assert isinstance(raw, DigestedIterable)
        # scalar depth 1 <= 2, inline
        assert raw.items[0] == 1
        # [2, 3] has depth 2 <= 2, so it stays inline too
        assert raw.items[1] == [2, 3]
        assert ds.load(key) == data

    def test_remaining_depth_2_destructures_deeper(self):
        """With remaining_depth=2, a list nested 3 deep is still destructured."""
        mem = Memory(storage={})
        ds = DestructuringStorage(mem, remaining_depth=2)
        data = [1, [[2]]]
        key = ds.save(data)
        raw = mem.load(key)
        assert isinstance(raw, DigestedIterable)
        assert raw.items[0] == 1
        # [[2]] has depth 3 > 2, gets a digest
        assert isinstance(raw.items[1], Digest)
        assert ds.load(key) == data

    def test_remaining_depth_dict(self):
        """remaining_depth works for dicts too."""
        mem = Memory(storage={})
        ds = DestructuringStorage(mem, remaining_depth=1)
        data = {"a": 1, "b": [2, 3]}
        key = ds.save(data)
        raw = mem.load(key)
        assert isinstance(raw, DigestedDict)
        # keys "a" and "b" are strings (depth 1), so inline
        # value 1 is scalar (depth 1), inline
        # value [2,3] has depth 2 > 1, gets a digest
        for k, v in raw.items.items():
            if not isinstance(k, Digest):
                # inline key
                assert isinstance(k, str)
        assert ds.load(key) == data

    def test_remaining_depth_tuple_preserves_type(self):
        """Tuples stay tuples through remaining_depth roundtrip."""
        mem = Memory(storage={})
        ds = DestructuringStorage(mem, remaining_depth=1)
        data = (1, 2, (3, 4))
        key = ds.save(data)
        loaded = ds.load(key)
        assert loaded == data
        assert isinstance(loaded, tuple)
        assert isinstance(loaded[2], tuple)

    def test_remaining_depth_reduces_storage_slots(self):
        """Higher remaining_depth should use fewer storage slots."""
        mem0 = Memory(storage={})
        ds0 = DestructuringStorage(mem0, remaining_depth=0)
        mem2 = Memory(storage={})
        ds2 = DestructuringStorage(mem2, remaining_depth=2)

        data = [1, 2, [3, 4]]
        ds0.save(data)
        ds2.save(data)

        # remaining_depth=2 should store fewer items because scalars and
        # the flat inner list [3,4] (depth 2) are inlined
        assert len(list(mem2.list())) < len(list(mem0.list()))

    def test_load_passthrough_non_digest(self):
        """_load returns non-Digest values as-is (inline values from mend)."""
        mem = Memory(storage={})
        ds = DestructuringStorage(mem)
        assert ds._load(42) == 42
        assert ds._load("hello") == "hello"
        assert ds._load([1, 2]) == [1, 2]

    def test_remaining_depth_empty_containers(self):
        """Empty containers with remaining_depth > 0 round-trip correctly."""
        mem = Memory(storage={})
        ds = DestructuringStorage(mem, remaining_depth=2)
        for data in [[], (), {}]:
            key = ds.save(data)
            loaded = ds.load(key)
            assert loaded == data
            assert type(loaded) == type(data)
