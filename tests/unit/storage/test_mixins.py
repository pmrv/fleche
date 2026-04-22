"""Unit tests for ValueMixin and CallMixin, plus coverage gaps in
KeyManagement/StorageBackend base classes.

Each mixin is exercised through a minimal composition with MemoryBackend so
tests stay independent of backend-specific behaviour.  DestructuringMixin and
threading mixins are intentionally absent so the mixin contract is visible
without additional layers.

Gaps covered here (previously untested in tests/unit/storage/):
  base.py:37        _resolve_prefix for-else branch (no differing char found)
  base.py:100-103   contains() short key not found → returns False
  base.py:121-128   shrink()
  base.py:154-159   StorageBackend._contains() default get-based implementation
  base.py:217-218   transform() except KeyError: continue
  base.py:267-270   CallMixin.query()

ValueMixin.save/load and CallMixin.save/load were tested via the high-level
ValueStorage/CallStorage fixture before #282 (first step); these tests
reinstate that coverage at the mixin level.
"""

import contextlib
from dataclasses import dataclass, field

import pytest

from fleche.call import Call, QueryCall
from fleche.digest import Digest, digest
from fleche.storage.base import (
    AmbiguousDigestError,
    CallMixin,
    StorageBackend,
    ValueMixin,
    _resolve_prefix,
)
from fleche.storage.memory import MemoryBackend


# ---------------------------------------------------------------------------
# Minimal composite classes (no DestructuringMixin, no thread-safety)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PlainValueMemory(ValueMixin, MemoryBackend):
    """ValueMixin wired directly to MemoryBackend; no DestructuringMixin."""


@dataclass(frozen=True)
class PlainCallMemory(CallMixin, MemoryBackend):
    """CallMixin wired directly to MemoryBackend."""


@dataclass
class MinimalBackend(StorageBackend):
    """Bare StorageBackend that does NOT override _contains, exercising the
    default get-based _contains implementation (base.py:154-159)."""
    storage: dict

    def put(self, value, key):
        self.storage[key] = value
        return key

    def get(self, key):
        if key not in self.storage:
            raise KeyError(key)
        return self.storage[key]

    def list(self):
        return list(self.storage.keys())

    def _evict(self, key):
        self.storage.pop(key, None)


@dataclass(frozen=True)
class _TrackingValueMemory(ValueMixin, MemoryBackend):
    """Records every key passed to _operation_context (append-only list field)."""
    _ctx_keys: list = field(default_factory=list, init=False, compare=False, repr=False)

    @contextlib.contextmanager
    def _operation_context(self, key):
        self._ctx_keys.append(str(key))
        with super()._operation_context(key):
            yield


@dataclass(frozen=True)
class _TrackingCallMemory(CallMixin, MemoryBackend):
    _ctx_keys: list = field(default_factory=list, init=False, compare=False, repr=False)

    @contextlib.contextmanager
    def _operation_context(self, key):
        self._ctx_keys.append(str(key))
        with super()._operation_context(key):
            yield


@dataclass(frozen=True)
class _PhantomCallMemory(CallMixin, MemoryBackend):
    """list() includes a phantom key that has no matching entry in storage,
    triggering the except KeyError: continue path in transform()."""

    def list(self):
        return [*super().list(), digest("__phantom__")]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _call(name="f", **extra):
    return Call(name=name, arguments={"x": 1, **extra}, result=42)


# ---------------------------------------------------------------------------
# ValueMixin.save
# ---------------------------------------------------------------------------

def test_value_mixin_save_auto_key_equals_digest():
    store = PlainValueMemory(storage={})
    value = [1, 2, 3]
    assert store.save(value) == digest(value)


def test_value_mixin_save_explicit_key_returned():
    store = PlainValueMemory(storage={})
    custom_key = digest("custom")
    assert store.save("hello", key=custom_key) == custom_key


def test_value_mixin_save_explicit_key_stored():
    store = PlainValueMemory(storage={})
    custom_key = digest("custom")
    store.save("hello", key=custom_key)
    assert store.load(custom_key) == "hello"


def test_value_mixin_save_explicit_key_does_not_fill_natural_slot():
    store = PlainValueMemory(storage={})
    value = 42
    store.save(value, key=digest("custom"))
    assert not store.contains(digest(value))


def test_value_mixin_save_enters_operation_context():
    store = _TrackingValueMemory(storage={})
    store.save("hello")
    assert len(store._ctx_keys) >= 1


# ---------------------------------------------------------------------------
# ValueMixin.load
# ---------------------------------------------------------------------------

def test_value_mixin_load_full_key():
    store = PlainValueMemory(storage={})
    key = store.save("test_value")
    assert store.load(key) == "test_value"


def test_value_mixin_load_short_key():
    store = PlainValueMemory(storage={})
    key = store.save(99)
    assert store.load(key[:8]) == 99


def test_value_mixin_load_missing_raises():
    store = PlainValueMemory(storage={})
    with pytest.raises(KeyError):
        store.load(digest("nonexistent"))


def test_value_mixin_load_enters_operation_context():
    store = _TrackingValueMemory(storage={})
    key = store.save("world")
    before = len(store._ctx_keys)
    store.load(key)
    assert len(store._ctx_keys) > before


# ---------------------------------------------------------------------------
# CallMixin.save
# ---------------------------------------------------------------------------

def test_call_mixin_save_derives_key_from_lookup_key():
    store = PlainCallMemory(storage={})
    call = _call()
    assert store.save(call) == call.to_lookup_key()


def test_call_mixin_save_overwrites_existing():
    """Saving the same call twice evicts the old entry — no duplicates."""
    store = PlainCallMemory(storage={})
    call = _call()
    store.save(call)
    store.save(call)
    assert len(list(store.list())) == 1


def test_call_mixin_save_updated_result_replaces():
    store = PlainCallMemory(storage={})
    c1 = Call(name="f", arguments={"x": 1}, result=1)
    c2 = Call(name="f", arguments={"x": 1}, result=2)
    store.save(c1)
    store.save(c2)
    assert store.load(c2.to_lookup_key()).result == 2
    assert len(list(store.list())) == 1


def test_call_mixin_save_enters_operation_context():
    store = _TrackingCallMemory(storage={})
    store.save(_call())
    assert len(store._ctx_keys) >= 1


# ---------------------------------------------------------------------------
# CallMixin.load
# ---------------------------------------------------------------------------

def test_call_mixin_load_full_key():
    store = PlainCallMemory(storage={})
    call = _call()
    key = store.save(call)
    assert store.load(key) == call


def test_call_mixin_load_short_key():
    store = PlainCallMemory(storage={})
    call = _call()
    key = store.save(call)
    assert store.load(key[:8]) == call


def test_call_mixin_load_missing_raises():
    store = PlainCallMemory(storage={})
    with pytest.raises(KeyError):
        store.load(digest("not_there"))


def test_call_mixin_load_enters_operation_context():
    store = _TrackingCallMemory(storage={})
    call = _call()
    key = store.save(call)
    before = len(store._ctx_keys)
    store.load(key)
    assert len(store._ctx_keys) > before


# ---------------------------------------------------------------------------
# CallMixin.query (base.py:267-270 — entirely untested before this file)
# ---------------------------------------------------------------------------

def test_call_mixin_query_empty_store():
    store = PlainCallMemory(storage={})
    assert list(store.query(QueryCall())) == []


def test_call_mixin_query_wildcard_returns_all():
    store = PlainCallMemory(storage={})
    store.save(_call("f"))
    store.save(_call("g"))
    assert len(list(store.query(QueryCall()))) == 2


def test_call_mixin_query_name_filter():
    store = PlainCallMemory(storage={})
    store.save(_call("target"))
    store.save(_call("other"))
    results = list(store.query(QueryCall(name="target")))
    assert len(results) == 1
    assert results[0].name == "target"


def test_call_mixin_query_no_match():
    store = PlainCallMemory(storage={})
    store.save(_call("f"))
    assert list(store.query(QueryCall(name="nonexistent"))) == []


# ---------------------------------------------------------------------------
# KeyManagement.contains with short key not found (base.py:100-103)
# ---------------------------------------------------------------------------

def test_contains_short_key_not_found_returns_false():
    store = PlainValueMemory(storage={})
    assert store.contains("abcd") is False


def test_contains_short_key_found():
    store = PlainValueMemory(storage={})
    key = store.save("x")
    assert store.contains(key[:8]) is True


# ---------------------------------------------------------------------------
# KeyManagement.shrink (base.py:121-128)
# ---------------------------------------------------------------------------

def test_shrink_returns_unambiguous_prefix():
    store = PlainValueMemory(storage={})
    key = store.save("only value")
    short = store.shrink(key)
    assert 4 <= len(short) < len(key)
    assert store.expand(short) == key


def test_shrink_two_keys_each_shrinkable():
    store = PlainValueMemory(storage={})
    k1 = store.save("alpha")
    k2 = store.save("beta")
    # Both keys differ at some position; each can be shrunk independently.
    assert store.expand(store.shrink(k1)) == k1
    assert store.expand(store.shrink(k2)) == k2


def test_shrink_ambiguous_raises():
    """Keys that share all but the last character cannot be shrunk to an
    unambiguous prefix shorter than the full key — shrink raises."""
    store = PlainValueMemory(storage={})
    k1, k2 = Digest("a" * 64), Digest("a" * 63 + "b")
    store.save("v1", key=k1)
    store.save("v2", key=k2)
    with pytest.raises(AmbiguousDigestError):
        store.shrink(k1)


# ---------------------------------------------------------------------------
# StorageBackend._contains default implementation (base.py:154-159)
# ---------------------------------------------------------------------------

def test_storage_backend_default_contains_true():
    store = MinimalBackend(storage={})
    key = digest("val")
    store.put("val", key)
    assert store._contains(key) is True


def test_storage_backend_default_contains_false():
    store = MinimalBackend(storage={})
    assert store._contains(digest("val")) is False


# ---------------------------------------------------------------------------
# CallStorage.transform KeyError handler (base.py:217-218)
# ---------------------------------------------------------------------------

def test_transform_skips_phantom_key():
    """transform() silently skips keys that raise KeyError on load."""
    store = _PhantomCallMemory(storage={})
    call = _call()
    store.save(call)
    store.transform()  # must not raise despite phantom key in list()
    assert store.load(call.to_lookup_key()) == call


# ---------------------------------------------------------------------------
# _resolve_prefix for-else branch (base.py:37)
# ---------------------------------------------------------------------------

def test_resolve_prefix_else_branch():
    """The for-else in _resolve_prefix fires when both candidates are
    identical (no differing character found in the zip loop)."""
    identical = Digest("a" * 64)
    with pytest.raises(AmbiguousDigestError):
        _resolve_prefix("aaaa", [identical, identical])
