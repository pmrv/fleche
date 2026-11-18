"""Destructuring of ``dtype=object`` numpy arrays (#1063).

fleche-numpy declares the destructurer through the ``fleche`` entry point
``destructure``.  Object arrays are destructured element-wise like lists,
keeping their shape.  Other arrays, structured ones with object fields
included, stay opaque.
"""

import pytest

np = pytest.importorskip("numpy")
pytest.importorskip("fleche_numpy")

import importlib.metadata
import logging
import subprocess
import sys
import threading
from types import SimpleNamespace

from fleche.digest import Digest, digest
from fleche.storage import destructuring
from fleche.storage.destructuring import DestructuringMixin
from fleche.storage.memory import ValueMemory
from fleche_numpy.destructure import DigestedArray, destructurers


def raw_entries(vm):
    """Raw (unmended) entries of *vm*, keyed by digest."""
    return {k: super(DestructuringMixin, vm).load(k) for k in vm.list()}


def same(a, b):
    """Deep equality that also compares array dtype, shape and type."""
    if isinstance(a, np.ndarray) or isinstance(b, np.ndarray):
        if type(a) is not type(b) or a.dtype != b.dtype or a.shape != b.shape:
            return False
        if a.dtype.kind == "O":
            return all(same(x, y) for x, y in zip(a.reshape(-1), b.reshape(-1)))
        return np.array_equal(a, b)
    if isinstance(a, (list, tuple)):
        return type(a) is type(b) and len(a) == len(b) and all(map(same, a, b))
    if isinstance(a, dict):
        return a.keys() == b.keys() and all(same(a[k], b[k]) for k in a)
    return a == b


def object_array(*items, shape=None):
    arr = np.empty(len(items), dtype=object)
    for i, item in enumerate(items):
        arr[i] = item
    return arr if shape is None else arr.reshape(shape)


VALUES = [
    np.arange(3),
    {"a": np.arange(3), "b": np.ones((2, 2))},
    [{"disp": np.arange(3), "forces": np.ones(3)} for _ in range(3)],
    object_array(1, [2, 3], np.arange(2)),
    [1, object_array(1, [2, [3]], None, "x", shape=(2, 2))],
    object_array([1, 2], shape=()),
    np.empty(0, dtype=object),
    [np.zeros(2, dtype=[("a", "O"), ("b", "i4")])],
]


@pytest.mark.parametrize("remaining_depth", [0, 1, 2, 3])
@pytest.mark.parametrize("value", VALUES, ids=lambda v: type(v).__name__)
def test_roundtrip_and_digest(value, remaining_depth):
    vm = ValueMemory({}, remaining_depth=remaining_depth)
    key = vm.save(value)
    assert key == digest(value)
    assert same(vm.load(key), value)


def test_plain_array_is_a_leaf():
    """An array without object fields inlines into its parent like an int."""
    arr = np.arange(3)
    vm = ValueMemory({}, remaining_depth=1)
    key = vm.save({"x": arr, "y": np.ones((2, 2))})
    assert set(vm.storage) == {key}
    assert same(vm.load(key), {"x": arr, "y": np.ones((2, 2))})


def test_plain_array_split_at_depth_zero():
    arr = np.arange(3)
    vm = ValueMemory({}, remaining_depth=0)
    vm.save([1, arr])
    assert digest(arr) in vm.storage


def test_records_of_arrays_fold_by_remaining_depth():
    """A list of records holding arrays: one entry per record at depth 1, one in all at 2."""
    value = [{"disp": np.full(3, i), "forces": np.ones(3) * i} for i in range(4)]
    counts = {}
    for depth in (1, 2):
        vm = ValueMemory({}, remaining_depth=depth)
        vm.save(value)
        counts[depth] = len(vm.storage)
    assert counts == {1: 5, 2: 1}


def test_object_array_inlines_plain_array():
    plain = np.arange(3)
    vm = ValueMemory({}, remaining_depth=1)
    key = vm.save(object_array(1, plain))
    assert set(vm.storage) == {key}
    assert type(vm.storage[key]) is np.ndarray


def test_object_array_destructured_like_list():
    inner = [2, 3]
    arr = object_array(1, inner)
    vm = ValueMemory({}, remaining_depth=1)
    key = vm.save(arr)
    raw = vm.storage[key]
    assert isinstance(raw, DigestedArray)
    assert raw.items.dtype.kind == "O" and raw.items.shape == arr.shape
    assert raw.items[0] == 1
    assert isinstance(raw.items[1], Digest)
    assert vm.load(raw.items[1]) == inner
    assert vm.child_digests(key) == {digest(inner)}


def test_object_array_shares_elements():
    shared = [2, 3]
    vm = ValueMemory({}, remaining_depth=1)
    vm.save(object_array(1, shared))
    vm.save([4, shared])
    assert vm.count_reuses()[digest(shared)] == 2


def test_object_array_of_scalars_stored_plain():
    vm = ValueMemory({}, remaining_depth=1)
    arr = object_array(1, "x", None)
    key = vm.save(arr)
    assert type(vm.storage[key]) is np.ndarray


def test_structured_object_array_stays_opaque():
    arr = np.zeros(2, dtype=[("a", "O"), ("b", "i4")])
    vm = ValueMemory({}, remaining_depth=99)
    vm.save([arr])
    assert digest(arr) in vm.storage


# ---- Registration through the entry point ----


def test_fleche_numpy_declares_its_destructurers():
    eps = importlib.metadata.entry_points(group="fleche", name="destructure")
    assert any(ep.load() is destructurers for ep in eps)


def test_entry_points_load_once():
    ValueMemory({}).save([1])
    registered = list(destructuring._DESTRUCTURERS)
    destructuring._load_entry_points()
    assert destructuring._DESTRUCTURERS == registered
    assert sum(d.fn is destructurers[0][1] for d in registered) == 1


def test_first_save_in_a_fresh_process_is_destructured():
    """The destructurer is registered before the first save, not after the first digest.

    Loaded with the digest hooks instead, the first object array of a process
    would be stored whole and only later ones split.
    """
    script = (
        "import numpy as np\n"
        "from fleche.storage.memory import ValueMemory\n"
        "arr = np.empty(2, dtype=object)\n"
        "arr[0], arr[1] = 1, [2, 3]\n"
        "vm = ValueMemory({})\n"
        "print(type(vm.storage[vm.save(arr)]).__qualname__)\n"
    )
    out = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "DigestedArray", out.stderr


@pytest.fixture
def fresh_registry(monkeypatch):
    """Reset the destructurer registry and the entry-point flag; restore both afterwards."""
    monkeypatch.setattr(destructuring, "_DESTRUCTURERS", list(destructuring._DESTRUCTURERS))
    monkeypatch.setattr(destructuring, "_ENTRY_POINTS_LOADED", False)
    return monkeypatch


class Tag:
    """A value no built-in destructurer handles: opaque unless something registers it."""

    def __digest__(self):
        return digest("Tag")

    def __eq__(self, other):
        return isinstance(other, Tag)


def _leaf(intern, value):
    return value, 0


def _entry_point(name, load):
    return SimpleNamespace(value=name, load=load)


def test_a_broken_entry_point_does_not_block_the_others(fresh_registry, caplog):
    def broken():
        raise ImportError("plugin missing a dependency")

    eps = [
        _entry_point("broken:destructurers", broken),
        _entry_point("good:destructurers", lambda: [(lambda v: isinstance(v, Tag), _leaf)]),
    ]
    fresh_registry.setattr(destructuring.importlib.metadata, "entry_points", lambda **kw: eps)

    vm = ValueMemory({})
    with caplog.at_level(logging.ERROR, logger=destructuring.__name__):
        key = vm.save([Tag(), 1])

    assert set(vm.storage) == {key}, "the good entry point was not registered"
    assert "broken:destructurers" in caplog.text


def test_a_save_waits_for_entry_points_another_thread_is_loading(fresh_registry):
    """A save racing the first load must not store values before the destructurers exist."""
    started, release = threading.Event(), threading.Event()

    def slow_load():
        started.set()
        release.wait(10)
        return [(lambda v: isinstance(v, Tag), _leaf)]

    fresh_registry.setattr(
        destructuring.importlib.metadata, "entry_points",
        lambda **kw: [_entry_point("slow:destructurers", slow_load)],
    )
    loader = threading.Thread(target=destructuring._load_entry_points)
    loader.start()
    assert started.wait(10)

    vm = ValueMemory({})
    saver = threading.Thread(target=vm.save, args=([Tag(), 1],))
    saver.start()
    saver.join(0.5)  # a save that does not wait finishes here, storing Tag whole
    release.set()
    loader.join(10)
    saver.join(10)

    assert len(vm.storage) == 1, "the save ran before the entry points were registered"


# ---- N-D arrays, subclasses, inlined wrappers ----


def test_2d_object_array_is_destructured_and_survives_gc():
    from fleche.caches import Cache
    from fleche.call import Call
    from fleche.storage.memory import CallMemory

    lists = [[1, 2], [3, 4], [5, 6], [7, 8]]
    arr = object_array(*lists, shape=(2, 2))
    cache = Cache(values=ValueMemory({}), calls=CallMemory({}))
    key = cache.save(Call(name="f", arguments={"x": 1}, result=arr))

    result_key = cache.calls.load(key).result
    raw = cache.values.storage[result_key]
    assert isinstance(raw, DigestedArray) and raw.items.shape == (2, 2)
    assert cache.values.child_digests(result_key) == {digest(v) for v in lists}

    assert cache.gc() == set()
    assert same(cache.load(key).result, arr)


@pytest.mark.parametrize("make", [
    lambda: np.matrix(object_array([1], [2], [3], [4], shape=(2, 2))),
    lambda: np.ma.masked_array(object_array([1, 2], [3, 4]), mask=[False, True]),
    lambda: np.ma.masked_array(object_array([1, 2], [3, 4]), mask=[False, False]),
], ids=["matrix", "masked", "unmasked"])
def test_object_array_subclasses_are_stored_whole(make):
    """reshape and element access differ on subclasses, so they are not taken apart."""
    value = make()
    vm = ValueMemory({})
    key = vm.save(value)
    assert type(vm.storage[key]) is type(value)
    loaded = vm.load(key)
    assert type(loaded) is type(value)
    assert digest(loaded) == digest(value)


def test_inlined_wrapper_inside_object_array_is_mended():
    vm = ValueMemory({}, remaining_depth=3)
    ref = vm.save((7, (8, 9)))
    arr = object_array([1, ref], "x")
    key = vm.save(arr)
    raw = vm.storage[key]
    assert isinstance(raw, DigestedArray)
    assert vm.child_digests(key) == {ref}
    loaded = vm.load(key)
    assert loaded[0] == [1, (7, (8, 9))] and loaded[1] == "x"

