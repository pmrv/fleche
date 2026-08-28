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
    __hash__ = object.__hash__


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


@pytest.fixture
def split_cache():
    """A Cache that destructures down to scalar leaves (remaining_depth=0),
    so every sub-key exists as its own entry for reachability checks."""
    return Cache(values=ValueMemory({}, remaining_depth=0), calls=CallMemory({}))


def test_gc_keeps_destructured_subtree(split_cache):
    """A call referencing a nested list must keep every key in its subtree."""
    call = Call(name="f", arguments={"xs": [1, [2, 3]]}, result=[4, 5])
    split_cache.save(call)

    keys_before = set(split_cache.values.list())
    evicted = split_cache.gc()

    assert evicted == set(), (
        "GC should retain the root and every transitive destructured sub-key. "
        f"Evicted: {evicted}; before: {keys_before}"
    )
    assert set(split_cache.values.list()) == keys_before


def test_gc_keeps_shared_subtree_referenced_by_one_call(split_cache):
    """A leaf shared between two structures stays alive if any parent is reachable."""
    shared = [2, 3]
    call = Call(name="f", arguments={"xs": [1, shared]}, result=None)
    split_cache.save(call)

    # Save another structure directly referencing `shared`, then orphan it
    # (no call points to it).  The shared subtree is still referenced by the
    # live call, so GC must keep it.
    other_key = split_cache.values.save([4, shared])
    assert other_key in split_cache.values.list()

    evicted = split_cache.gc()

    assert other_key in evicted, "Orphaned top-level container should be evicted"
    # The shared [2, 3] leaf and its scalar children must survive
    shared_key = digest([2, 3])
    assert shared_key in split_cache.values.list()
    assert digest(2) in split_cache.values.list()
    assert digest(3) in split_cache.values.list()


def test_gc_evicts_deeply_unreachable_structure(split_cache):
    """A whole orphan tree — root and every descendant — should be swept."""
    # Seed a reachable call so the cache isn't entirely empty.
    split_cache.save(Call(name="live", arguments={"x": 42}, result=0))
    reachable_before = set(split_cache.values.list())

    orphan_root = split_cache.values.save([[10, 20], [30, 40]])
    orphan_leaf_only = digest(10)
    assert orphan_root in split_cache.values.list()
    assert orphan_leaf_only in split_cache.values.list()

    evicted = split_cache.gc()

    # Everything that was only reachable from `orphan_root` is gone.
    assert orphan_root in evicted
    assert orphan_leaf_only in evicted
    # Previously-live keys still present.
    assert reachable_before.issubset(set(split_cache.values.list()))


# ---- Tests below exercise GC's tolerance of entries vanishing mid-sweep ----
#
# `gc()` is a three-pass mark-and-sweep over live storage: it lists call keys
# and loads each, walks `child_digests` over the marked frontier, then evicts
# every unmarked value key.  Each pass re-reads storage after the listing that
# drove it, so any entry can disappear in between — another process running
# `gc()`/`evict()` concurrently, or a call record left pointing at a value that
# is already gone.  All three passes answer that with `except KeyError:
# continue`: a vanished entry is skipped, never a crash mid-sweep that would
# leave value storage half-collected.


def test_gc_skips_call_reference_missing_from_value_storage(split_cache):
    """A call pointing at an absent value must not abort the sweep.

    The marking pass seeds its frontier from the digests named by call
    records, then asks value storage for each one's children.  A call record
    that outlived its value — evicted directly, or lost to a partial restore —
    makes that ``child_digests`` lookup raise ``KeyError``.  GC must treat the
    dangling reference as a leaf and keep sweeping, so genuine orphans are
    still collected.
    """
    call = Call(name="f", arguments={"x": 1}, result=2)
    key = split_cache.save(call)
    dangling = split_cache.calls.load(key).result
    split_cache.values.evict(dangling)
    orphan = split_cache.values.save("nobody references me")

    evicted = split_cache.gc()

    assert evicted == {orphan}
    assert dangling not in split_cache.values.list()


def test_gc_skips_call_records_evicted_after_listing():
    """A call key listed but gone by the time GC loads it is skipped.

    ``calls.list()`` is a snapshot; a concurrent ``Cache.evict`` can drop a
    record before the marking pass reaches it.  The vanished record
    contributes no reachable digests and must not propagate its ``KeyError``
    out of ``gc()``.
    """

    class VanishingCallMemory(CallMemory):
        """Call storage whose listed keys are all gone on ``load``."""

        __hash__ = object.__hash__

        def load(self, key):
            raise KeyError(key)

    cache = Cache(values=ValueMemory({}), calls=VanishingCallMemory({}))
    cache.save(Call(name="f", arguments={"x": 1}, result=2))
    assert list(cache.calls.list()), "precondition: the record is still listed"
    values_before = set(cache.values.list())

    evicted = cache.gc()

    # The unreadable record marks nothing, so every value is swept as orphaned.
    assert evicted == values_before
    assert set(cache.values.list()) == set()


def test_gc_omits_values_evicted_concurrently_from_its_result():
    """A value that disappears before GC evicts it is not reported as evicted.

    The returned set is GC's record of what it actually removed; a key that a
    concurrent sweep already took raises ``KeyError`` on ``evict`` and must be
    left out rather than double-counted.
    """

    class AlreadyGoneValueMemory(ValueMemory):
        """Value storage that reports every eviction as a lost race."""

        __hash__ = object.__hash__

        def evict(self, key):
            raise KeyError(key)

    cache = Cache(values=AlreadyGoneValueMemory({}), calls=CallMemory({}))
    orphan = cache.values.save("nobody references me")

    evicted = cache.gc()

    assert evicted == set()
    assert orphan in cache.values.list()
