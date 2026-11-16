"""Regression test for issue #1063 (the ``None`` part).

https://github.com/pmrv/fleche/issues/1063

Destructuring treated only numbers, ``str`` and ``bytes`` as scalars (depth 0).
``None``, dates and times, ``np.bool_`` and ``pd.NA`` fell through to the opaque
case (depth ∞), so every occurrence got an entry of its own at every
``remaining_depth`` — one file write per ``Optional`` field left at ``None``.
They are scalars now and inline into their parent like an ``int``.
"""

import datetime

import pytest

from fleche.digest import digest
from fleche.storage.memory import ValueMemory

SCALARS = [
    None,
    datetime.date(2026, 11, 16),
    datetime.datetime(2026, 11, 16, 12, 30),
    datetime.time(12, 30),
    datetime.timedelta(seconds=5),
    datetime.timezone.utc,
]


def _numpy_scalars():
    np = pytest.importorskip("numpy")
    return [np.bool_(True), np.float64(1.5), np.int32(3)]


def _pandas_scalars():
    pd = pytest.importorskip("pandas")
    return [pd.NA, pd.Timestamp("2026-11-16"), pd.Timedelta(seconds=5)]


@pytest.mark.parametrize("value", SCALARS, ids=repr)
def test_builtin_scalar_inlines(value):
    vm = ValueMemory({}, remaining_depth=1)
    key = vm.save({"k": value})
    assert len(vm.storage) == 1
    assert vm.load(key) == {"k": value}


@pytest.mark.parametrize("make", [_numpy_scalars, _pandas_scalars])
def test_foreign_scalar_inlines(make):
    for value in make():
        vm = ValueMemory({}, remaining_depth=1)
        key = vm.save({"k": value})
        assert len(vm.storage) == 1, value
        loaded = vm.load(key)["k"]
        assert loaded is value or loaded == value


@pytest.mark.parametrize("remaining_depth", [0, 1, 2])
def test_split_does_not_change_digest(remaining_depth):
    value = {"a": None, "b": [None, datetime.date(2026, 11, 16)]}
    vm = ValueMemory({}, remaining_depth=remaining_depth)
    assert vm.save(value) == digest(value)
    assert vm.load(digest(value)) == value


def test_none_split_at_depth_zero():
    """``remaining_depth=0`` still splits every leaf, ``None`` included."""
    vm = ValueMemory({}, remaining_depth=0)
    vm.save([None])
    assert digest(None) in vm.storage
