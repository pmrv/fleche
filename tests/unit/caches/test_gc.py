"""Tests for Cache.gc() — brute-force reachability-based value eviction."""

import pytest

from fleche import call
from fleche.call import Call, PreparedCall
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


# ---- Calls in flight: prepared arguments are roots until commit or abandon ----


def test_gc_keeps_arguments_of_a_call_in_flight(gc_cache):
    """A sweep during the function body must not evict the sealed arguments.

    ``prepare`` stores the arguments before the body runs, precisely so the
    record cannot be keyed on post-mutation content — but for the whole
    duration of the body no record references them yet.  Without the in-flight
    roots ``gc`` reclaims them as orphans and the eventual ``commit`` files a
    record whose arguments are dangling digests.
    """
    prepared = gc_cache.prepare(Call(name="f", arguments={"x": "an argument"}))

    assert gc_cache.gc() == set()  # body "runs" here

    key = prepared.commit("a result")
    assert gc_cache.load(key).arguments["x"] == "an argument"


def test_gc_evicts_arguments_of_an_abandoned_call(gc_cache):
    """Abandoning releases the roots: the arguments are orphans again."""
    prepared = gc_cache.prepare(Call(name="f", arguments={"x": "an argument"}))
    arg_key = digest("an argument")
    assert arg_key in gc_cache.values.list()

    prepared.abandon()

    assert arg_key in gc_cache.gc()


def test_gc_evicts_arguments_after_commit_returns(gc_cache):
    """Committing hands the roots over to the record, and holds nothing else.

    Once the record references them the registry must let go, or a long-lived
    ``PreparedCall`` object would pin values forever.  Evicting the record and
    sweeping is the observable check.
    """
    prepared = gc_cache.prepare(Call(name="f", arguments={"x": "an argument"}))
    key = prepared.commit("a result")
    gc_cache.evict(key)

    assert digest("an argument") in gc_cache.gc()


def test_gc_keeps_nested_arguments_of_a_call_in_flight(split_cache):
    """In-flight roots seed the transitive walk, not just the top-level keys."""
    prepared = split_cache.prepare(Call(name="f", arguments={"x": [[1, 2], [3, 4]]}))

    assert split_cache.gc() == set()

    key = prepared.commit(None)
    assert split_cache.load(key).arguments["x"] == [[1, 2], [3, 4]]


def test_gc_keeps_arguments_of_a_call_in_flight_through_a_wrapper(gc_cache):
    """Wrapper rebinding must not drop the registration.

    ``CacheWrapper.prepare`` returns ``replace(inner.prepare(call), cache=self)``
    — a *new* object — so registering in ``prepare`` alone would leave only the
    inner one registered, and that one is garbage the moment ``replace``
    returns.
    """
    import gc as _gc

    from fleche.caches import RefreshingCache

    wrapper = RefreshingCache(gc_cache)
    prepared = wrapper.prepare(Call(name="f", arguments={"x": "an argument"}))
    _gc.collect()  # drop the inner PreparedCall replace() left behind

    assert gc_cache.gc() == set()
    assert digest("an argument") in gc_cache.values.list()
    prepared.abandon()


def test_in_flight_registry_does_not_leak_dropped_calls(gc_cache):
    """The registry is weak: a prepared call nobody finished falls out."""
    import gc as _gc

    from fleche.call import in_flight_digests

    gc_cache.prepare(Call(name="f", arguments={"x": "an argument"}))
    _gc.collect()

    assert in_flight_digests() == set()


def test_gc_is_safe_against_concurrent_prepares(gc_cache):
    """Sweeping while other threads admit calls must not raise.

    Scoped to what the sweep actually guarantees: the registry is a plain
    mapping that ``gc`` reads, so a concurrent ``prepare`` must not resize it
    mid-iteration, and neither side may blow up.  Value fidelity under a
    concurrent sweep is *not* asserted here — a narrow window remains between
    storing a value and registering the call that owns it, pinned deterministically
    by ``test_gc_may_evict_a_value_stored_but_not_yet_registered`` below.  An
    earlier version of this test asserted fidelity and was flaky on CI for
    exactly that reason.
    """
    import threading

    stop = threading.Event()
    errors: list[BaseException] = []

    def preparer(i):
        try:
            while not stop.is_set():
                prepared = gc_cache.prepare(Call(name="f", arguments={"x": f"arg-{i}"}))
                prepared.commit(i)
        except BaseException as e:  # pragma: no cover - only on a real race
            errors.append(e)

    threads = [threading.Thread(target=preparer, args=(i,)) for i in range(4)]
    for t in threads:
        t.start()
    try:
        for _ in range(200):
            gc_cache.gc()
    finally:
        stop.set()
        for t in threads:
            t.join()

    assert not errors, errors


def test_gc_keeps_a_call_that_commits_mid_sweep(gc_cache, monkeypatch):
    """A call finishing *between* two of the sweep's reads must survive.

    ``commit`` deregisters only after ``save`` has filed the record, so the
    registry read and the record read overlap in time — reading the roots
    first means a call that commits in the gap is caught by the roots.  Reading
    the records first (the original order) leaves it covered by neither, and
    its arguments are swept out from under a record that references them.
    Forced rather than raced: the commit is driven from inside the roots read.
    """
    prepared = gc_cache.prepare(Call(name="f", arguments={"x": "an argument"}))
    committed = {}

    # Drive the commit from the *record* read, so it lands after that read
    # whichever order the sweep uses.  With the roots read first (current
    # order) the registration was still live when the roots were taken, so the
    # value survives; with the records read first it is already deregistered by
    # the time the roots are taken, and nothing covers it.
    # Patched on the class: the storages are frozen dataclasses, so the hook
    # cannot go on the instance.
    storage_cls = type(gc_cache.calls)
    real_list = storage_cls.list

    def list_then_commit(self):
        records = list(real_list(self))
        if "key" not in committed:
            committed["key"] = prepared.commit("a result")
        return records

    monkeypatch.setattr(storage_cls, "list", list_then_commit)
    gc_cache.gc()
    monkeypatch.undo()

    assert gc_cache.load(committed["key"]).arguments["x"] == "an argument"


def test_gc_may_evict_a_value_stored_but_not_yet_registered(gc_cache, monkeypatch):
    """The one window the sweep does not close, pinned so it stays known.

    ``prepare`` stores the argument values and only then registers the call as
    a gc root.  A sweep that reads its candidates and roots inside that gap
    sees the value but not its owner, and reclaims it; the later commit files a
    record with a dangling reference.  This is the same window the one-shot
    ``save`` has always had between storing values and filing the record —
    bounded by a storage write rather than by a function body — and closing it
    would need a lock shared by every writer.

    Asserted so the limit is documented behaviour rather than folklore: if
    someone closes it, this test should fail and be deleted.
    """
    import threading

    started = threading.Event()
    release = threading.Event()
    real_post_init = PreparedCall.__post_init__

    def stall_before_registering(self):
        # Values are already stored; registration has not happened yet.
        started.set()
        release.wait(5)
        real_post_init(self)

    monkeypatch.setattr(PreparedCall, "__post_init__", stall_before_registering)

    out = {}

    def worker():
        prepared = gc_cache.prepare(Call(name="f", arguments={"x": "an argument"}))
        out["key"] = prepared.commit("a result")

    t = threading.Thread(target=worker)
    t.start()
    try:
        assert started.wait(5)
        evicted = gc_cache.gc()
    finally:
        release.set()
        t.join()

    assert digest("an argument") in evicted
    assert gc_cache.load(out["key"]).arguments["x"] == digest("an argument")
