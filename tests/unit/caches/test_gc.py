"""Tests for Cache.gc() — brute-force reachability-based value eviction."""

import pytest

from fleche.call import Call
from fleche.caches import Cache
from fleche.digest import digest
from fleche.storage.base import ValueMixin
from fleche.storage.memory import CallMemory, MemoryBackend, ValueMemory


class FlatValueMemory(ValueMixin, MemoryBackend):
    """Memory-backed value storage without destructuring.

    Stores values opaquely — no ``DestructuringMixin``, so it does not satisfy
    :class:`fleche.storage.destructuring.HasChildDigests`.  Used to exercise
    the GC path that walks only direct call references.
    """


@pytest.fixture(params=["destructuring", "flat"])
def gc_cache(request):
    """A fresh in-memory Cache, parametrised over destructuring vs flat values."""
    if request.param == "destructuring":
        return Cache(values=ValueMemory({}), calls=CallMemory({}))
    return Cache(values=FlatValueMemory({}), calls=CallMemory({}))


def test_gc_empty_cache_is_noop(gc_cache):
    assert gc_cache.gc() == set()


def test_gc_retains_values_referenced_by_calls(gc_cache):
    call = Call(name="f", arguments={"x": 1}, result=2)
    key = gc_cache.save(call)

    evicted = gc_cache.gc()

    assert evicted == set()
    assert gc_cache.contains(key)
    loaded = gc_cache.load(key)
    assert loaded.arguments["x"] == 1
    assert loaded.result == 2


def test_gc_evicts_orphan_value(gc_cache):
    orphan_key = gc_cache.values.save("nobody references me")
    assert orphan_key in gc_cache.values.list()

    evicted = gc_cache.gc()

    assert evicted == {orphan_key}
    assert orphan_key not in gc_cache.values.list()


def test_gc_preserves_call_records(gc_cache):
    call_a = Call(name="a", arguments={"x": 1}, result=2)
    call_b = Call(name="b", arguments={"y": [3, 4]}, result=5)
    key_a = gc_cache.save(call_a)
    key_b = gc_cache.save(call_b)
    # Add an orphan value for good measure.
    gc_cache.values.save("orphan")

    gc_cache.gc()

    assert gc_cache.contains(key_a)
    assert gc_cache.contains(key_b)


def test_gc_returns_evicted_keys(gc_cache):
    gc_cache.save(Call(name="f", arguments={"x": 1}, result=None))

    orphan_a = gc_cache.values.save("orphan-a")
    orphan_b = gc_cache.values.save("orphan-b")

    evicted = gc_cache.gc()

    assert evicted == {orphan_a, orphan_b}


# ---- Tests below exercise destructuring-specific reachability behaviour ----


def test_gc_keeps_destructured_subtree(clean_cache):
    """A call referencing a nested list must keep every key in its subtree."""
    call = Call(name="f", arguments={"xs": [1, [2, 3]]}, result=[4, 5])
    clean_cache.save(call)

    keys_before = set(clean_cache.values.list())
    evicted = clean_cache.gc()

    assert evicted == set(), (
        "GC should retain the root and every transitive destructured sub-key. "
        f"Evicted: {evicted}; before: {keys_before}"
    )
    assert set(clean_cache.values.list()) == keys_before


def test_gc_keeps_shared_subtree_referenced_by_one_call(clean_cache):
    """A leaf shared between two structures stays alive if any parent is reachable."""
    shared = [2, 3]
    call = Call(name="f", arguments={"xs": [1, shared]}, result=None)
    clean_cache.save(call)

    # Save another structure directly referencing `shared`, then orphan it
    # (no call points to it).  The shared subtree is still referenced by the
    # live call, so GC must keep it.
    other_key = clean_cache.values.save([4, shared])
    assert other_key in clean_cache.values.list()

    evicted = clean_cache.gc()

    assert other_key in evicted, "Orphaned top-level container should be evicted"
    # The shared [2, 3] leaf and its scalar children must survive
    shared_key = digest([2, 3])
    assert shared_key in clean_cache.values.list()
    assert digest(2) in clean_cache.values.list()
    assert digest(3) in clean_cache.values.list()


def test_gc_evicts_deeply_unreachable_structure(clean_cache):
    """A whole orphan tree — root and every descendant — should be swept."""
    # Seed a reachable call so the cache isn't entirely empty.
    clean_cache.save(Call(name="live", arguments={"x": 42}, result=0))
    reachable_before = set(clean_cache.values.list())

    orphan_root = clean_cache.values.save([[10, 20], [30, 40]])
    orphan_leaf_only = digest(10)
    assert orphan_root in clean_cache.values.list()
    assert orphan_leaf_only in clean_cache.values.list()

    evicted = clean_cache.gc()

    # Everything that was only reachable from `orphan_root` is gone.
    assert orphan_root in evicted
    assert orphan_leaf_only in evicted
    # Previously-live keys still present.
    assert reachable_before.issubset(set(clean_cache.values.list()))
