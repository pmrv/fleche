"""End-to-end workflow tests for Path-by-content caching.

These mirror the canonical "functions that accept and produce files and
directories via paths" scenario (see ``notebooks/Files.ipynb``) but assert
*correctness* rather than merely "runs without error": cache hits are proven by
counting body executions, and content-addressed deduplication is proven by
inspecting the value store.

Parametrized over an in-memory and an on-disk (pickle) cache so the opaque
``FileBlob`` / ``DirectoryBlob`` records are exercised through real
serialization, not just deepcopy.
"""

from pathlib import Path

import pytest

from fleche import fleche, cache
from fleche.digest import digest
from fleche.caches import Cache
from fleche.storage import (
    ValueMemory,
    CallMemory,
    ValuePickleFile,
    CallPickleFile,
)


@pytest.fixture(params=["memory", "cloudpickle"])
def paths_cache(request, tmp_path):
    if request.param == "memory":
        return Cache(ValueMemory({}), CallMemory({}))
    return Cache(
        ValuePickleFile.with_cloudpickle(tmp_path / "values"),
        CallPickleFile.with_cloudpickle(tmp_path / "calls"),
    )


def _relmap(root: Path) -> dict[str, bytes]:
    return {
        p.relative_to(root).as_posix(): p.read_bytes()
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


def test_file_producer_runs_once_and_roundtrips(paths_cache, tmp_path):
    """A cached file producer executes once; the cached result is a readable Path."""
    runs = []

    @fleche
    def produce(content):
        runs.append(content)
        f = tmp_path / f"out-{content}.txt"
        f.write_text(content)
        return f

    with cache(paths_cache):
        first = produce("payload")
        assert isinstance(first, Path)
        assert first.read_text() == "payload"

        second = produce("payload")
        assert isinstance(second, Path)
        assert second.read_text() == "payload"

    assert runs == ["payload"], "second call should have been served from cache"


def test_directory_producer_roundtrips_tree(paths_cache, tmp_path):
    """A cached directory producer round-trips a full nested tree by content."""
    runs = []

    @fleche
    def build(seed):
        runs.append(seed)
        d = tmp_path / f"tree-{seed}"
        d.mkdir()
        (d / "top.txt").write_text(seed)
        (d / "sub").mkdir()
        (d / "sub" / "leaf.bin").write_bytes(seed.encode() * 3)
        return d

    expected = {
        "top.txt": b"seed",
        "sub/leaf.bin": b"seedseedseed",
    }

    with cache(paths_cache):
        first = build("seed")
        assert _relmap(first) == expected

        second = build("seed")
        assert second.is_dir()
        assert _relmap(second) == expected

    assert runs == ["seed"]


def test_producer_consumer_chain_caches(paths_cache, tmp_path):
    """A Path flowing producer -> consumer: both stages cache on repeat input."""
    writes, parses = [], []

    @fleche
    def write(content):
        writes.append(content)
        f = tmp_path / f"w-{content}.txt"
        f.write_text(content)
        return f

    @fleche
    def parse(f: Path):
        parses.append(f.name)
        return f.read_text().upper()

    with cache(paths_cache):
        assert parse(write("hi")) == "HI"
        # write hits cache (same content) and so does parse (same file content),
        # even though the second write returns a freshly materialized TempPath.
        assert parse(write("hi")) == "HI"

    assert writes == ["hi"]
    assert parses == ["w-hi.txt"]


def test_shared_file_body_is_deduplicated(paths_cache, tmp_path):
    """A file body shared by two produced directories is reused, not re-stored."""
    shared = b"shared-body"
    one, two = b"one-only", b"two-only"

    @fleche
    def build(tag, unique):
        d = tmp_path / f"d-{tag}"
        d.mkdir()
        (d / "shared").write_bytes(shared)
        (d / "unique").write_bytes(unique)
        return d

    with cache(paths_cache):
        build("a", one)
        keys_after_a = set(paths_cache.values.list())
        assert digest(shared) in keys_after_a, "shared body stored when first dir is produced"

        build("b", two)
        keys_after_b = set(paths_cache.values.list())

    new_keys = keys_after_b - keys_after_a
    # The second directory's genuinely new content shows up...
    assert digest(two) in new_keys
    # ...but the shared body is content-addressed and reused, not re-stored.
    assert digest(shared) not in new_keys
