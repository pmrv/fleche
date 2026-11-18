"""``split_level``: values of about ``2**split_level`` bytes or more get an entry of their own (#1063).

Size is judged per destructurer through ``should_split(value, level)``, and by
``len`` for ``bytes``/``str``.  A split value keeps its depth, so its parent
still folds by ``remaining_depth`` and holds it by reference.
"""

from types import SimpleNamespace

import pytest

from fleche.caches import Cache
from fleche.call import Call
from fleche.config import storage_from_config, storage_to_config
from fleche.digest import digest
from fleche.storage import destructuring
from fleche.storage.memory import CallMemory, ValueMemory


def store(value, **kwargs):
    vm = ValueMemory({}, **kwargs)
    key = vm.save(value)
    assert key == digest(value)
    return vm, key


@pytest.mark.parametrize("make", [lambda n: "x" * n, lambda n: b"x" * n], ids=["str", "bytes"])
def test_scalars_split_by_length(make):
    vm, key = store({"big": make(16), "small": make(15)}, split_level=4)
    assert vm.child_digests(key) == {digest(make(16))}
    assert vm.load(key) == {"big": make(16), "small": make(15)}


def test_unset_never_splits():
    vm, key = store({"s": "x" * 100_000})
    assert set(vm.storage) == {key}


def test_a_split_value_keeps_its_depth():
    """The inner list still folds into the root; it holds the big string by reference."""
    big = "x" * 64
    vm, key = store([[1, big]], remaining_depth=3, split_level=6)
    assert set(vm.storage) == {key, digest(big)}
    assert vm.child_digests(key) == {digest(big)}
    assert vm.load(key) == [[1, big]]


def test_gc_keeps_a_split_value():
    big = "x" * 64
    cache = Cache(values=ValueMemory({}, remaining_depth=3, split_level=6), calls=CallMemory({}))
    key = cache.save(Call(name="f", arguments={"x": 1}, result=[[1, big]]))
    assert cache.gc() == set()
    assert cache.load(key).result == [[1, big]]


def test_lower_levels_split_more():
    value = {n: "x" * n for n in (1, 10, 100, 1000)}
    split = []
    for level in (12, 9, 6, 3, 0):
        vm, key = store(value, split_level=level)
        split.append(vm.child_digests(key))
    assert all(a <= b for a, b in zip(split, split[1:]))
    assert split[0] == set() and len(split[-1]) == 4


def test_the_top_level_value_is_stored_once():
    vm, key = store("x" * 64, split_level=0)
    assert set(vm.storage) == {key}


@pytest.mark.parametrize("bad", [-1, 1.5, "20", True])
def test_split_level_is_validated(bad):
    with pytest.raises(ValueError, match="split_level"):
        ValueMemory({}, split_level=bad)


# ---- registrations ----


class Blob:
    def __init__(self, size):
        self.size = size

    def __digest__(self):
        return digest(("Blob", self.size))

    def __eq__(self, other):
        return isinstance(other, Blob) and other.size == self.size


@pytest.fixture
def blob_leaf(monkeypatch):
    monkeypatch.setattr(destructuring, "_DESTRUCTURERS", list(destructuring._DESTRUCTURERS))
    destructuring.register_destructurer(
        lambda v: isinstance(v, Blob), lambda intern, v: (v, 0), lambda v, level: v.size >= 1 << level
    )


def test_a_registered_should_split_decides(blob_leaf):
    vm, key = store([Blob(8), Blob(7)], split_level=3)
    assert vm.child_digests(key) == {digest(Blob(8))}


def test_without_should_split_a_type_never_splits_by_size(monkeypatch):
    monkeypatch.setattr(destructuring, "_DESTRUCTURERS", list(destructuring._DESTRUCTURERS))
    destructuring.register_destructurer(lambda v: isinstance(v, Blob), lambda intern, v: (v, 0))
    vm, key = store([Blob(1 << 20)], split_level=0)
    assert set(vm.storage) == {key}


def test_entry_points_may_carry_should_split(monkeypatch):
    monkeypatch.setattr(destructuring, "_DESTRUCTURERS", list(destructuring._DESTRUCTURERS))
    monkeypatch.setattr(destructuring, "_ENTRY_POINTS_LOADED", False)
    entry = (lambda v: isinstance(v, Blob), lambda intern, v: (v, 0), lambda v, level: v.size >= 1 << level)
    monkeypatch.setattr(
        destructuring.importlib.metadata, "entry_points",
        lambda **kw: [SimpleNamespace(value="blob:destructurers", load=lambda: [entry])],
    )
    vm, key = store([Blob(8), Blob(7)], split_level=3)
    assert vm.child_digests(key) == {digest(Blob(8))}


# ---- sister packages ----


def test_numpy_arrays_split_by_nbytes():
    np = pytest.importorskip("numpy")
    pytest.importorskip("fleche_numpy")
    big, small = np.zeros(128), np.zeros(127)  # 1024 and 1016 bytes
    vm, key = store({"big": big, "small": small}, split_level=10)
    assert vm.child_digests(key) == {digest(big)}


def test_pandas_containers_split_by_memory_usage():
    pd = pytest.importorskip("pandas")
    pytest.importorskip("fleche_pandas")
    big = pd.DataFrame({"a": range(10_000)})
    small = pd.Series([1.0])
    vm, key = store([big, small], split_level=12)
    assert vm.child_digests(key) == {digest(big)}
    loaded = vm.load(key)
    assert loaded[0].equals(big) and loaded[1].equals(small)


def test_atoms_split_by_array_bytes():
    pytest.importorskip("fleche_ase")
    from ase import Atoms

    big = Atoms("Cu" * 200, positions=[[0, 0, i] for i in range(200)])
    small = Atoms("Cu", positions=[[0, 0, 0]])
    vm, key = store([big, small], split_level=12)
    assert vm.child_digests(key) == {digest(big)}


# ---- configuration ----


@pytest.mark.parametrize("backend", ["memory", "pickle", "cloudpickle", "dill", "bagofholding_hdf"])
def test_split_level_round_trips_through_config(tmp_path, backend):
    if backend == "bagofholding_hdf":
        pytest.importorskip("bagofholding")
    if backend in ("cloudpickle", "dill"):
        pytest.importorskip(backend)
    extra = {} if backend == "memory" else {"root": str(tmp_path / "values")}
    s = storage_from_config({"type": backend, "split_level": 20, **extra}, "value")
    assert s.split_level == 20
    cfg = storage_to_config(s)
    assert cfg["split_level"] == 20
    assert storage_from_config(cfg, "value").split_level == 20


def test_split_level_is_omitted_from_config_when_unset():
    assert "split_level" not in storage_to_config(ValueMemory({}))
