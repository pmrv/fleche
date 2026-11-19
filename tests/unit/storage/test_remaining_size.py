"""``remaining_size``: a value holding about that many bytes gets an entry of its own (#1063).

A node's size is its own bytes-ish estimate (``size`` on its destructurer, ``len``
for ``bytes``/``str``, a word for other scalars) plus the sizes of the children
inlined into it; a child stored apart counts nothing.  Splitting by size adds
to ``remaining_depth``: a node is inlined only while under both.
"""

from types import SimpleNamespace

import pytest

from fleche.caches import Cache
from fleche.call import Call
from fleche.config import storage_from_config, storage_to_config
from fleche.digest import digest
from fleche.storage import destructuring
from fleche.storage.memory import CallMemory, ValueMemory

DEEP = 99  # remaining_depth high enough that only size decides


def store(value, **kwargs):
    vm = ValueMemory({}, **kwargs)
    key = vm.save(value)
    assert key == digest(value)
    assert vm.load(key) == value
    return vm, key


@pytest.mark.parametrize("make", [lambda n: "x" * n, lambda n: b"x" * n], ids=["str", "bytes"])
def test_scalars_count_their_length(make):
    vm, key = store({"big": make(16), "small": make(15)}, remaining_depth=DEEP, remaining_size=16)
    assert vm.child_digests(key) == {digest(make(16))}


def test_inlined_children_add_up():
    """No string reaches the limit on its own, but the list holding them does."""
    record = ["x" * 10] * 4
    vm, key = store({"record": record, "n": 1}, remaining_depth=DEEP, remaining_size=32)
    assert vm.child_digests(key) == {digest(record)}
    assert set(vm.storage) == {key, digest(record)}


def test_a_child_stored_apart_counts_nothing():
    """The big string is split off, so the list holding it stays small and inlines."""
    big = "x" * 64
    vm, key = store([[1, big]], remaining_depth=DEEP, remaining_size=32)
    assert set(vm.storage) == {key, digest(big)}
    assert vm.child_digests(key) == {digest(big)}


def test_depth_still_splits():
    vm, key = store([[1, 2]], remaining_depth=1, remaining_size=1 << 20)
    assert digest([1, 2]) in vm.storage


def test_a_size_never_reached_leaves_the_depth_only_layout():
    """With sizes summed but never reaching the limit, depth alone decides, as when unset."""
    value = {"a": ["x" * 100] * 5, "b": [[1, 2], [3]]}
    for depth in (0, 1, 2, DEEP):
        unset = ValueMemory({}, remaining_depth=depth)
        huge = ValueMemory({}, remaining_depth=depth, remaining_size=1 << 62)
        unset.save(value)
        huge.save(value)
        assert unset.storage == huge.storage


def test_gc_keeps_an_entry_split_by_size():
    record = ["x" * 10] * 4
    values = ValueMemory({}, remaining_depth=DEEP, remaining_size=32)
    cache = Cache(values=values, calls=CallMemory({}))
    key = cache.save(Call(name="f", arguments={"x": 1}, result={"record": record}))
    assert cache.gc() == set()
    assert cache.load(key).result == {"record": record}


def test_the_top_level_value_is_stored_once():
    vm, key = store("x" * 64, remaining_size=0)
    assert set(vm.storage) == {key}


def test_namedtuples_count_their_fields():
    from collections import namedtuple

    Pair = namedtuple("Pair", "a b")
    pair = Pair("x" * 20, "y" * 20)
    vm, key = store([pair, 1], remaining_depth=DEEP, remaining_size=32)
    assert vm.child_digests(key) == {digest(pair)}


@pytest.mark.parametrize("bad", [-1, 1.5, "32KiB", True])
def test_remaining_size_is_validated(bad):
    with pytest.raises(ValueError, match="remaining_size"):
        ValueMemory({}, remaining_size=bad)


# ---- registrations ----


class Blob:
    def __init__(self, size):
        self.size = size

    def __digest__(self):
        return digest(("Blob", self.size))

    def __eq__(self, other):
        return isinstance(other, Blob) and other.size == self.size


@pytest.fixture
def fresh_registry(monkeypatch):
    monkeypatch.setattr(destructuring, "_DESTRUCTURERS", list(destructuring._DESTRUCTURERS))
    return monkeypatch


def test_a_registered_size_counts(fresh_registry):
    destructuring.register_destructurer(lambda v: isinstance(v, Blob), lambda intern, v: (v, 0), lambda v: v.size)
    vm, key = store([Blob(8), Blob(7)], remaining_depth=DEEP, remaining_size=8)
    assert vm.child_digests(key) == {digest(Blob(8))}


def test_registered_sizes_add_up_in_a_parent(fresh_registry):
    destructuring.register_destructurer(lambda v: isinstance(v, Blob), lambda intern, v: (v, 0), lambda v: v.size)
    inner = [Blob(5), Blob(5)]  # 10 together; the int counts a word, 8
    vm, key = store([inner, 1], remaining_depth=DEEP, remaining_size=9)
    assert vm.child_digests(key) == {digest(inner)}


def test_without_a_size_a_type_counts_nothing(fresh_registry):
    destructuring.register_destructurer(lambda v: isinstance(v, Blob), lambda intern, v: (v, 0))
    vm, key = store([Blob(1 << 20)], remaining_depth=DEEP, remaining_size=1)
    assert set(vm.storage) == {key}


def test_entry_points_may_carry_a_size(fresh_registry):
    fresh_registry.setattr(destructuring, "_ENTRY_POINTS_LOADED", False)
    entry = (lambda v: isinstance(v, Blob), lambda intern, v: (v, 0), lambda v: v.size)
    fresh_registry.setattr(
        destructuring.importlib.metadata, "entry_points",
        lambda **kw: [SimpleNamespace(value="blob:destructurers", load=lambda: [entry])],
    )
    vm, key = store([Blob(8), Blob(7)], remaining_depth=DEEP, remaining_size=8)
    assert vm.child_digests(key) == {digest(Blob(8))}


# ---- sister packages ----


def test_numpy_arrays_count_nbytes():
    np = pytest.importorskip("numpy")
    pytest.importorskip("fleche_numpy")
    big, small = np.zeros(128), np.zeros(127)  # 1024 and 1016 bytes
    vm = ValueMemory({}, remaining_depth=DEEP, remaining_size=1024)
    key = vm.save({"big": big, "small": small})
    assert vm.child_digests(key) == {digest(big)}


def test_records_of_small_arrays_fold_until_they_add_up():
    np = pytest.importorskip("numpy")
    pytest.importorskip("fleche_numpy")
    records = [{"a": np.full(64, i), "b": np.full(64, -i)} for i in range(3)]  # 1 KiB each
    vm = ValueMemory({}, remaining_depth=DEEP, remaining_size=1024)
    key = vm.save(records)
    assert vm.child_digests(key) == {digest(r) for r in records}


def test_pandas_containers_count_memory_usage():
    pd = pytest.importorskip("pandas")
    pytest.importorskip("fleche_pandas")
    big = pd.DataFrame({"a": range(10_000)})
    small = pd.Series([1.0])
    vm = ValueMemory({}, remaining_depth=DEEP, remaining_size=4096)
    key = vm.save([big, small])
    assert vm.child_digests(key) == {digest(big)}
    loaded = vm.load(key)
    assert loaded[0].equals(big) and loaded[1].equals(small)


def test_atoms_count_their_array_bytes():
    pytest.importorskip("fleche_ase")
    from ase import Atoms

    big = Atoms("Cu" * 200, positions=[[0, 0, i] for i in range(200)])
    small = Atoms("Cu", positions=[[0, 0, 0]])
    vm = ValueMemory({}, remaining_depth=DEEP, remaining_size=4096)
    key = vm.save([big, small])
    assert vm.child_digests(key) == {digest(big)}


# ---- configuration ----


@pytest.mark.parametrize("backend", ["memory", "pickle", "cloudpickle", "dill", "bagofholding_hdf"])
def test_remaining_size_round_trips_through_config(tmp_path, backend):
    if backend == "bagofholding_hdf":
        pytest.importorskip("bagofholding")
    if backend in ("cloudpickle", "dill"):
        pytest.importorskip(backend)
    extra = {} if backend == "memory" else {"root": str(tmp_path / "values")}
    s = storage_from_config({"type": backend, "remaining_size": 32768, **extra}, "value")
    assert s.remaining_size == 32768
    cfg = storage_to_config(s)
    assert cfg["remaining_size"] == 32768
    assert storage_from_config(cfg, "value").remaining_size == 32768


def test_remaining_size_is_omitted_from_config_when_unset():
    assert "remaining_size" not in storage_to_config(ValueMemory({}))
