"""Path-by-content storage through the *default* value storages.

The committed ``test_paths.py`` exercises a hand-built ``PathDM`` over
``MemoryBackend`` only.  These tests prove that wiring ``PathValueMixin`` into
the real default classes (``ValueMemory``, ``ValuePickleFile``,
``ValueBagOfHoldingH5File``) actually works end-to-end — in particular that the
``FileBlob`` (name, content) records, ``DirectoryBlob`` trees, and plain-bytes
content survive each backend's serialization (pickle, H5), not just in-memory
deepcopy.
"""

from pathlib import Path

import pytest

from fleche import fleche, cache
from fleche.digest import digest
from fleche.caches import Cache, DigestedDict
from fleche.storage import (
    ValueMemory,
    ValuePickleFile,
    ValueBagOfHoldingH5File,
    CallMemory,
    PathValueMixin,
)
from fleche.storage.destructuring import DigestedMapping


# ---- helpers -------------------------------------------------------------

def _make_tree(root: Path) -> Path:
    """Create *root* and fill it with a small nested directory tree; return *root*."""
    root.mkdir(parents=True, exist_ok=True)
    (root / "a.txt").write_bytes(b"hello")
    sub = root / "sub"
    sub.mkdir()
    (sub / "b.bin").write_bytes(b"\x00\x01\x02world")
    (sub / "deep").mkdir()
    (sub / "deep" / "c").write_bytes(b"deep-bytes")
    return root


def _relmap(root: Path) -> dict[str, bytes]:
    """Map every file under *root* to ``{relative_posix_path: bytes}``."""
    return {
        p.relative_to(root).as_posix(): p.read_bytes()
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


# ---- the default value storages carry PathValueMixin ---------------------

@pytest.mark.parametrize(
    "cls", [ValueMemory, ValuePickleFile, ValueBagOfHoldingH5File]
)
def test_default_value_storage_has_path_mixin_in_mro(cls):
    assert PathValueMixin in cls.__mro__
    names = [c.__name__ for c in cls.__mro__]
    # PathValueMixin sits between DestructuringMixin and ValueMixin so
    # Destructure's recursion lands on it, and it stores blobs via ValueMixin.
    assert (
        names.index("DestructuringMixin")
        < names.index("PathValueMixin")
        < names.index("ValueMixin")
    )


# ---- round-trips across every real backend -------------------------------

def test_file_path_roundtrip(value_storage, tmp_path):
    p = tmp_path / "f.txt"
    p.write_bytes(b"contents")

    key = value_storage.save(p)
    # A file is keyed on (name, content); that equals the path's own digest.
    assert key == digest(p)

    loaded = value_storage.load(key)
    assert isinstance(loaded, Path)
    assert loaded.read_bytes() == b"contents"
    assert loaded.name == "f.txt"          # name preserved by default — no wrapping


def test_directory_tree_roundtrip(value_storage, tmp_path):
    src = _make_tree(tmp_path / "src")
    expected = _relmap(src)

    key = value_storage.save(src)
    loaded = value_storage.load(key)

    assert isinstance(loaded, Path)
    assert loaded.is_dir()
    assert _relmap(loaded) == expected


def test_path_nested_in_dict_roundtrip(value_storage, tmp_path):
    src = _make_tree(tmp_path / "src")
    expected = _relmap(src)

    wrapper = {"tree": src, "label": "x", "n": 3}
    key = value_storage.save(wrapper)
    loaded = value_storage.load(key)

    assert loaded["label"] == "x"
    assert loaded["n"] == 3
    assert isinstance(loaded["tree"], Path)
    assert _relmap(loaded["tree"]) == expected


def test_content_addressed_file_dedup(value_storage, tmp_path):
    """A file body shared by two directories is stored exactly once."""
    shared = b"shared-body"
    one, two = b"one", b"two"

    d1 = tmp_path / "d1"
    d1.mkdir()
    (d1 / "x").write_bytes(shared)
    (d1 / "y").write_bytes(one)

    d2 = tmp_path / "d2"
    d2.mkdir()
    (d2 / "x").write_bytes(shared)
    (d2 / "z").write_bytes(two)

    k1 = value_storage.save(d1)
    k2 = value_storage.save(d2)

    keys = set(value_storage.list())
    # File bodies are plain bytes keyed by content; only one copy of `shared`,
    # and the two directory trees are distinct.
    assert keys == {
        digest(shared),
        digest(one),
        digest(two),
        k1,
        k2,
    }


def test_save_load_save_is_idempotent(value_storage, tmp_path):
    """Re-saving a materialized TempPath reproduces the same content key."""
    src = _make_tree(tmp_path / "src")

    key = value_storage.save(src)
    loaded = value_storage.load(key)
    key2 = value_storage.save(loaded)

    assert key2 == key


# ---- end-to-end through a Cache + @fleche --------------------------------

def test_cache_end_to_end_path_roundtrip(tmp_path):
    """A cached function producing a Path: tree stored by content, cache hit on repeat."""
    runs = []

    @fleche
    def build(name, payload):
        runs.append(name)
        d = tmp_path / f"out-{name}"
        d.mkdir()
        (d / "data.txt").write_text(payload)
        (d / "nested").mkdir()
        (d / "nested" / "more.bin").write_bytes(payload.encode() * 2)
        return d

    with cache(Cache(ValueMemory({}), CallMemory({}))):
        first = build("a", "hello")
        assert isinstance(first, Path)
        assert (first / "data.txt").read_text() == "hello"

        second = build("a", "hello")
        assert isinstance(second, Path)
        assert (second / "data.txt").read_text() == "hello"
        assert (second / "nested" / "more.bin").read_bytes() == b"hellohello"

    # The body ran exactly once; the second call was served from cache.
    assert runs == ["a"]


def test_cache_path_argument_roundtrip(tmp_path):
    """A cached function consuming a Path argument hits cache on repeat input."""
    parsed = []

    @fleche
    def parse(f: Path):
        parsed.append(f.name)
        return f.read_text().upper()

    p = tmp_path / "in.txt"
    p.write_text("abc")

    with cache(Cache(ValueMemory({}), CallMemory({}))):
        assert parse(p) == "ABC"
        assert parse(p) == "ABC"

    # Same Path content => one execution.
    assert parsed == ["in.txt"]


def test_downstream_consumer_needs_no_branching(tmp_path):
    """A file keeps its name through the cache, so a plain consumer sees the right suffix.

    No NamedPath, no isinstance: ``inspect`` is an ordinary path consumer and its
    ``.suffix`` check holds even when ``produce`` is served from cache.
    """
    runs = []

    @fleche
    def produce(seed):
        runs.append(("produce", seed))
        p = tmp_path / f"{seed}.json"
        p.write_text(f'{{"seed": "{seed}"}}')
        return p

    @fleche
    def inspect(path):
        runs.append(("inspect", path.suffix))
        assert path.suffix == ".json"
        return path.stem

    with cache(Cache(ValueMemory({}), CallMemory({}))):
        assert inspect(produce("alpha")) == "alpha"
        assert inspect(produce("alpha")) == "alpha"   # produce cached -> alpha.json

    assert runs == [("produce", "alpha"), ("inspect", ".json")]


def test_renaming_does_not_duplicate_the_content_blob(tmp_path):
    """Renaming a file (same bytes, new name) adds only a record, never re-stores the body."""
    store = ValueMemory({})
    body = b"the unchanging body" * 100

    original = tmp_path / "draft.txt"
    original.write_bytes(body)
    store.save(original)
    keys_before = set(store.list())
    assert digest(body) in keys_before, "content body stored on first save"

    renamed_path = tmp_path / "final.txt"
    original.rename(renamed_path)
    store.save(renamed_path)

    added = set(store.list()) - keys_before
    assert len(added) == 1                              # just the (name, content) record
    assert digest(body) not in added                   # body reused, not duplicated


# ---- backward-compat alias ----------------------------------------------

def test_digesteddict_alias_is_digestedmapping():
    assert DigestedDict is DigestedMapping
