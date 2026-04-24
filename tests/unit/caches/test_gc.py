"""Tests for Cache.gc() — brute-force reachability-based value eviction."""

from dataclasses import dataclass

import pytest

from fleche.call import Call
from fleche.caches import Cache
from fleche.digest import Digest, digest
from fleche.storage import ValueVoid, CallVoid
from fleche.storage.memory import CallMemory, ValueMemory


def _make_cache() -> Cache:
    return Cache(values=ValueMemory({}), calls=CallMemory({}))


def test_gc_empty_cache_is_noop():
    c = _make_cache()
    assert c.gc() == set()


def test_gc_retains_values_referenced_by_calls():
    c = _make_cache()
    call = Call(name="f", arguments={"x": 1}, result=2)
    key = c.save(call)

    evicted = c.gc()

    assert evicted == set()
    assert c.contains(key)
    loaded = c.load(key)
    assert loaded.arguments["x"] == 1
    assert loaded.result == 2


def test_gc_evicts_orphan_value():
    c = _make_cache()
    orphan_key = c.values.save("nobody references me")
    assert orphan_key in c.values.list()

    evicted = c.gc()

    assert evicted == {orphan_key}
    assert orphan_key not in c.values.list()


def test_gc_keeps_destructured_subtree():
    """A call referencing a nested list must keep every key in its subtree."""
    c = _make_cache()
    call = Call(name="f", arguments={"xs": [1, [2, 3]]}, result=[4, 5])
    c.save(call)

    keys_before = set(c.values.list())
    evicted = c.gc()

    assert evicted == set(), (
        "GC should retain the root and every transitive destructured sub-key. "
        f"Evicted: {evicted}; before: {keys_before}"
    )
    assert set(c.values.list()) == keys_before


def test_gc_keeps_shared_subtree_referenced_by_one_call():
    """A leaf shared between two structures stays alive if any parent is reachable."""
    c = _make_cache()
    shared = [2, 3]
    call = Call(name="f", arguments={"xs": [1, shared]}, result=None)
    c.save(call)

    # Save another structure directly referencing `shared`, then orphan it
    # (no call points to it).  The shared subtree is still referenced by the
    # live call, so GC must keep it.
    other_key = c.values.save([4, shared])
    assert other_key in c.values.list()

    evicted = c.gc()

    assert other_key in evicted, "Orphaned top-level container should be evicted"
    # The shared [2, 3] leaf and its scalar children must survive
    shared_key = digest([2, 3])
    assert shared_key in c.values.list()
    assert digest(2) in c.values.list()
    assert digest(3) in c.values.list()


def test_gc_evicts_deeply_unreachable_structure():
    """A whole orphan tree — root and every descendant — should be swept."""
    c = _make_cache()
    # Seed a reachable call so the cache isn't entirely empty.
    c.save(Call(name="live", arguments={"x": 42}, result=0))
    reachable_before = set(c.values.list())

    orphan_root = c.values.save([[10, 20], [30, 40]])
    orphan_leaf_only = digest(10)
    assert orphan_root in c.values.list()
    assert orphan_leaf_only in c.values.list()

    evicted = c.gc()

    # Everything that was only reachable from `orphan_root` is gone.
    assert orphan_root in evicted
    assert orphan_leaf_only in evicted
    # Previously-live keys still present.
    assert reachable_before.issubset(set(c.values.list()))


def test_gc_preserves_call_records():
    c = _make_cache()
    call_a = Call(name="a", arguments={"x": 1}, result=2)
    call_b = Call(name="b", arguments={"y": [3, 4]}, result=5)
    key_a = c.save(call_a)
    key_b = c.save(call_b)
    # Add an orphan value for good measure.
    c.values.save("orphan")

    c.gc()

    assert c.contains(key_a)
    assert c.contains(key_b)


def test_gc_on_non_destructuring_value_storage():
    """Value storages without child_digests() (e.g. ValueVoid) are handled gracefully."""

    @dataclass(frozen=True)
    class _Stub:
        """Minimal ValueStorage-ish stand-in: list + evict + no child_digests."""

        _store: dict

        def list(self):
            return tuple(self._store.keys())

        def save(self, value, key=None):
            k = Digest(digest(value)) if key is None else key
            self._store[k] = value
            return k

        def load(self, key):
            return self._store[key]

        def evict(self, key):
            self._store.pop(Digest(key), None)

        def contains(self, key):
            return Digest(key) in self._store

        def expand(self, key):
            return Digest(key)

        def shrink(self, key):
            return Digest(key)

    store = _Stub(_store={})
    c = Cache(values=store, calls=CallMemory({}))

    # Two directly-referenced values + one orphan.
    ref_key = store.save("referenced")
    orphan_key = store.save("orphan")
    from fleche.call import DigestedCall

    c.calls.save(
        DigestedCall(name="f", arguments={"x": ref_key}, result=None)
    )

    evicted = c.gc()

    assert evicted == {orphan_key}
    assert ref_key in store.list()


def test_gc_returns_evicted_keys():
    c = _make_cache()
    c.save(Call(name="f", arguments={"x": 1}, result=None))

    orphan_a = c.values.save("orphan-a")
    orphan_b = c.values.save("orphan-b")

    evicted = c.gc()

    assert evicted == {orphan_a, orphan_b}
