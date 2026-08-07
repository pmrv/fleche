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


# ---- Path values: blob records reference their content, and gc must see it ----


@pytest.fixture
def path_cache():
    return Cache(values=ValueMemory({}), calls=CallMemory({}))


@pytest.fixture
def a_file(tmp_path):
    f = tmp_path / "data.txt"
    f.write_text("file content")
    return f


@pytest.fixture
def a_tree(tmp_path):
    d = tmp_path / "tree"
    (d / "sub").mkdir(parents=True)
    (d / "top.txt").write_text("top")
    (d / "sub" / "leaf.bin").write_bytes(b"leaf")
    return d


@pytest.mark.parametrize("which", ["file", "tree", "both-nested"])
def test_gc_keeps_the_content_behind_a_stored_path(path_cache, a_file, a_tree, which):
    """A stored path is a name plus a *reference*; gc must follow the reference.

    The blob records carry the digests of the content ``bytes``.  If the walk
    cannot see them the content looks unreferenced, gc reclaims it, and the
    entry is destroyed — the load then raises ``KeyError``, which the wrapper
    reports as an ordinary cache miss, so the loss is silent.
    """
    result = {"file": a_file, "dir": a_tree} if which == "both-nested" else (
        a_file if which == "file" else a_tree
    )
    call = Call(name="f", arguments={"x": 1}, result=result)
    key = path_cache.save(call)

    assert path_cache.gc() == set()

    loaded = path_cache.load(key).result
    if which == "file":
        assert loaded.read_text() == "file content"
    elif which == "tree":
        assert (loaded / "top.txt").read_text() == "top"
        assert (loaded / "sub" / "leaf.bin").read_bytes() == b"leaf"
    else:
        assert loaded["file"].read_text() == "file content"
        assert (loaded["dir"] / "sub" / "leaf.bin").read_bytes() == b"leaf"


def test_gc_still_evicts_an_orphaned_path(path_cache, a_file):
    """The fix must not make path content unconditionally reachable."""
    orphan = path_cache.values.save(a_file)
    assert orphan in path_cache.gc()


def test_child_digests_reports_a_blob_s_content(path_cache, a_file, a_tree):
    """The blob layer declares its own references, unmended."""
    file_key = path_cache.values.save(a_file)
    assert path_cache.values.child_digests(file_key), "FileBlob reported no children"

    tree_key = path_cache.values.save(a_tree)
    children = path_cache.values.child_digests(tree_key)
    assert len(children) == 2, "DirectoryBlob should reference both of its entries"


def test_reachability_walk_does_not_materialize_paths(path_cache, a_file, monkeypatch):
    """Inspecting the graph must not build temp trees for every stored path.

    ``child_digests`` reads through ``load_raw``, so the path layer's
    materialization is skipped: gc over a large cache would otherwise copy
    every stored file to disk just to ask what it points at.
    """
    from fleche.storage import paths as paths_mod

    path_cache.save(Call(name="f", arguments={"x": 1}, result=a_file))

    calls = []
    real = paths_mod.TempPath.mkdtemp
    monkeypatch.setattr(
        paths_mod.TempPath, "mkdtemp",
        classmethod(lambda cls: (calls.append(1), real())[1]),
    )
    path_cache.gc()
    path_cache.values.count_reuses()
    assert calls == [], f"walk materialized {len(calls)} temp tree(s)"
