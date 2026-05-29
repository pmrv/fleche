"""Tests for the _operation_context hook on KeyManagement / StorageBackend."""

import contextlib
from dataclasses import dataclass

from fleche.storage import Intent, SerializingMixin, ValueMixin
from fleche.storage.memory import MemoryBackend


@dataclass(frozen=True)
class _PlainValueMemory(ValueMixin, MemoryBackend): ...


def test_mixin_composition_chains_through_super():
    """A mixin that stacks on top of SerializingMixin must chain via super()."""
    entered = []

    class TrackingMixin(SerializingMixin):
        @contextlib.contextmanager
        def _operation_context(self, key, *, intent=Intent.WRITE):
            entered.append(key)
            with super()._operation_context(key, intent=intent):
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
        def _operation_context(self, key, *, intent=Intent.WRITE):
            called_with.append(("enter", str(key)[:4]))
            with super()._operation_context(key, intent=intent):
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


def test_intent_default_is_write():
    """The default intent passed to _operation_context is Intent.WRITE."""
    intents_seen = []

    class TrackingMixin(SerializingMixin):
        @contextlib.contextmanager
        def _operation_context(self, key, *, intent=Intent.WRITE):
            intents_seen.append(intent)
            with super()._operation_context(key, intent=intent):
                yield

    @dataclass(frozen=True)
    class Tracked(TrackingMixin, _PlainValueMemory):
        pass

    store = Tracked(storage={})
    store.save(1)
    assert all(i == Intent.WRITE for i in intents_seen)
    assert all(isinstance(i, Intent) for i in intents_seen)


def test_intent_propagates_through_mixin_chain():
    """intent is forwarded correctly through every layer in the MRO."""
    collected = []

    class OuterMixin(SerializingMixin):
        @contextlib.contextmanager
        def _operation_context(self, key, *, intent=Intent.WRITE):
            collected.append(("outer", intent))
            with super()._operation_context(key, intent=intent):
                yield

    @dataclass(frozen=True)
    class Tracked(OuterMixin, _PlainValueMemory):
        pass

    store = Tracked(storage={})
    with store._operation_context("k", intent=Intent.WRITE):
        pass

    assert collected == [("outer", Intent.WRITE)]
