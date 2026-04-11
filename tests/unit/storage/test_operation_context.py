"""Tests for the _operation_context hook on KeyManagement / StorageBackend."""

import contextlib
from dataclasses import dataclass

from fleche.storage import SerializingMixin, ValueMixin
from fleche.storage.memory import MemoryBackend


@dataclass(frozen=True)
class _PlainValueMemory(ValueMixin, MemoryBackend): ...


def test_mixin_composition_chains_through_super():
    """A mixin that stacks on top of SerializingMixin must chain via super()."""
    entered = []

    class TrackingMixin(SerializingMixin):
        @contextlib.contextmanager
        def _operation_context(self, key):
            entered.append(key)
            with super()._operation_context(key):
                yield

    @dataclass(frozen=True)
    class Tracked(TrackingMixin, _PlainValueMemory):
        pass

    store = Tracked(storage={})
    k = store.save(42)
    _ = store.load(k)

    # _operation_context must have been called for both save and load.
    assert len(entered) >= 2


def test_base_operation_context_is_noop():
    """The default _operation_context in KeyManagement yields without side effects."""
    store = _PlainValueMemory(storage={})
    with store._operation_context("somekey"):
        pass  # should not raise or do anything


def test_operation_context_wraps_evict_and_contains():
    """evict and contains both enter _operation_context."""
    called_with = []

    class TrackingMixin(SerializingMixin):
        @contextlib.contextmanager
        def _operation_context(self, key):
            called_with.append(("enter", str(key)[:4]))
            with super()._operation_context(key):
                yield
            called_with.append(("exit", str(key)[:4]))

    @dataclass(frozen=True)
    class Tracked(TrackingMixin, _PlainValueMemory):
        pass

    store = Tracked(storage={})
    key = store.save(99)
    called_with.clear()

    store.contains(key)
    assert any(e[0] == "enter" for e in called_with)

    called_with.clear()
    store.evict(key)
    assert any(e[0] == "enter" for e in called_with)
