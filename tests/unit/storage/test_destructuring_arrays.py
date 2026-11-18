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
import subprocess
import sys

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


def test_plain_array_stays_opaque():
    arr = np.arange(3)
    vm = ValueMemory({}, remaining_depth=99)
    vm.save([1, arr])
    assert digest(arr) in vm.storage


def test_object_array_references_plain_array():
    plain = np.arange(3)
    vm = ValueMemory({}, remaining_depth=1)
    key = vm.save(object_array(1, plain))
    assert isinstance(vm.storage[key], DigestedArray)
    assert vm.child_digests(key) == {digest(plain)}


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
    assert sum(fn is destructurers[0][1] for _, fn in registered) == 1


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
    out = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "DigestedArray"

