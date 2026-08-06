import gc
import tempfile
from dataclasses import dataclass
from pathlib import Path

import pytest

from collections import namedtuple

from fleche.digest import digest, Indigestible
from fleche.storage import ValueMixin, DestructuringMixin
from fleche.storage.memory import MemoryBackend
from fleche.storage.destructuring import DigestedMapping
from fleche.storage.paths import (
    TempPath,
    PathValueMixin,
    FileBlob,
    DirectoryBlob,
    find_path,
)


def test_mkdtemp_returns_temp_path():
    p = TempPath.mkdtemp()
    assert isinstance(p, TempPath)


def test_mkdtemp_directory_exists():
    p = TempPath.mkdtemp()
    assert p.exists()
    assert p.is_dir()


def test_mkdtemp_cleanup_on_del():
    p = TempPath.mkdtemp()
    path_str = str(p)
    assert Path(path_str).exists()
    del p
    gc.collect()
    assert not Path(path_str).exists()


def test_derived_path_shares_temp_root():
    p = TempPath.mkdtemp()
    child = p / "subdir"
    assert isinstance(child, TempPath)
    assert getattr(child, "_temp_root", None) is getattr(p, "_temp_root", None)


def test_derived_path_keeps_temp_dir_alive():
    p = TempPath.mkdtemp()
    child = p / "child.txt"
    path_str = str(p)
    del p
    gc.collect()
    # child still holds a reference to _temp_root, so directory must still exist
    assert Path(path_str).exists()
    del child
    gc.collect()
    assert not Path(path_str).exists()


def test_cleanup_after_all_derived_refs_gone():
    p = TempPath.mkdtemp()
    a = p / "a"
    b = p / "b" / "c"
    path_str = str(p)
    del p
    del a
    gc.collect()
    assert Path(path_str).exists()
    del b
    gc.collect()
    assert not Path(path_str).exists()


def test_path_operations_work():
    p = TempPath.mkdtemp()
    child = p / "file.txt"
    child.write_text("hello")
    assert child.read_text() == "hello"


def test_with_suffix_shares_temp_root():
    p = TempPath.mkdtemp()
    suffixed = (p / "file").with_suffix(".txt")
    assert isinstance(suffixed, TempPath)
    assert getattr(suffixed, "_temp_root", None) is getattr(p, "_temp_root", None)


def test_parent_shares_temp_root():
    p = TempPath.mkdtemp()
    child = p / "a" / "b"
    parent = child.parent
    assert isinstance(parent, TempPath)
    assert getattr(parent, "_temp_root", None) is getattr(p, "_temp_root", None)


def test_multiple_mkdtemp_calls_independent():
    p1 = TempPath.mkdtemp()
    p2 = TempPath.mkdtemp()
    assert p1 != p2
    path1_str = str(p1)
    del p1
    gc.collect()
    assert not Path(path1_str).exists()
    assert p2.exists()


def test_temp_path_is_path_subclass():
    p = TempPath.mkdtemp()
    assert isinstance(p, Path)


def test_no_temp_root_on_plain_construction():
    # Constructing TempPath without mkdtemp should not set _temp_root
    # (and should not raise on attribute access)
    with tempfile.TemporaryDirectory() as tmpdir:
        p = TempPath(tmpdir)
        assert getattr(p, "_temp_root", None) is None


def test_derived_from_plain_has_no_temp_root():
    with tempfile.TemporaryDirectory() as tmpdir:
        p = TempPath(tmpdir)
        child = p / "child"
        assert getattr(child, "_temp_root", None) is None


# ---- DirectoryBlob / FileBlob basics ----


def test_directoryblob_is_opaque_to_destructuring():
    """DirectoryBlob is neither a dict subclass nor a dataclass — DestructuringMixin leaves it alone."""
    from dataclasses import is_dataclass
    assert not isinstance(DirectoryBlob({}), dict)
    assert not is_dataclass(DirectoryBlob({}))


def test_directoryblob_repr_distinguishes_from_dict():
    """Repr shows the wrapper class explicitly."""
    db = DirectoryBlob({"a": digest(b"x")})
    assert repr(db).startswith("DirectoryBlob(")
    nested = DirectoryBlob({"sub": digest(b"y")})
    assert repr(nested).startswith("DirectoryBlob(")


def test_directoryblob_digest_distinct_from_plain_dict():
    """DirectoryBlob salts its digest with the class name so it never collides with a bare dict."""
    contents = {"a": digest(b"x"), "b": digest(b"y")}
    db = DirectoryBlob(contents)
    assert digest(db) != digest(contents)


def test_directoryblob_equality_and_unhashable():
    """DirectoryBlobs with equal contents are equal; instances are unhashable."""
    a = DirectoryBlob({"a": digest(b"x")})
    b = DirectoryBlob({"a": digest(b"x")})
    assert a == b
    with pytest.raises(TypeError):
        hash(a)


def test_fileblob_record_digests_on_name_and_content():
    """FileBlob pairs a basename with a content digest; both are part of its identity."""
    c = digest(b"hello")
    assert digest(FileBlob("a.txt", c)) != digest(FileBlob("b.txt", c))  # name matters
    assert digest(FileBlob("a.txt", c)) == digest(FileBlob("a.txt", c))  # stable
    assert digest(FileBlob("a.txt", c)) != c                              # not the bare content


def test_fileblob_equality_repr_unhashable():
    c = digest(b"x")
    assert FileBlob("a", c) == FileBlob("a", c)
    assert FileBlob("a", c) != FileBlob("b", c)
    assert repr(FileBlob("a", c)).startswith("FileBlob(")
    with pytest.raises(TypeError):
        hash(FileBlob("a", c))


# ---- PathValueMixin + DestructuringMixin composition ----
# MRO contract: DestructuringMixin sits above PathValueMixin so that
# Destructure's recursion (via super().save) lands here when it encounters a
# nested Path.  PathValueMixin owns the directory traversal end-to-end and
# never re-enters self.save / self.load — every storage call uses super(),
# so there's no load-context ambiguity when other transform mixins compose
# below it.


@dataclass(frozen=True)
class PathDM(DestructuringMixin, PathValueMixin, ValueMixin, MemoryBackend):
    """Test storage: Destructure -> PathValue -> ValueMixin -> MemoryBackend."""
    __hash__ = object.__hash__


@pytest.fixture
def pds():
    return PathDM(storage={})


def test_toplevel_directory_path_stored_as_opaque_directoryblob(pds, tmp_path):
    """Saving a directory Path yields a DirectoryBlob stored verbatim (not destructured)."""
    (tmp_path / "a.txt").write_bytes(b"hello")
    (tmp_path / "b.txt").write_bytes(b"world")

    key = pds.save(tmp_path)
    raw = pds.storage[key]
    assert type(raw) is DirectoryBlob
    assert set(raw.contents) == {"a.txt", "b.txt"}


def test_toplevel_file_path_stored_as_fileblob_record(pds, tmp_path):
    """A file Path stores as content bytes (deduped) plus a FileBlob(name, content) record."""
    p = tmp_path / "f.txt"
    p.write_bytes(b"contents")
    key = pds.save(p)
    raw = pds.storage[key]
    assert type(raw) is FileBlob
    assert raw.name == "f.txt"
    # Content lives separately as plain bytes under its own content digest.
    assert raw.content == digest(b"contents")
    assert pds.storage[digest(b"contents")] == b"contents"
    # The file's key is (name, content) == the path's own digest, not the raw bytes'.
    assert key == digest(p)
    assert key != digest(b"contents")


def test_toplevel_file_path_roundtrip_preserves_name(pds, tmp_path):
    """Save → load of a file Path returns a path with the original bytes AND name."""
    p = tmp_path / "f.txt"
    p.write_bytes(b"contents")
    loaded = pds.load(pds.save(p))
    assert isinstance(loaded, Path)
    assert loaded.read_bytes() == b"contents"
    assert loaded.name == "f.txt"      # name preserved by default — no wrapping
    assert loaded.suffix == ".txt"


def test_toplevel_directory_path_roundtrip(pds, tmp_path):
    """Save → load of a directory Path materializes the tree; root name is mangled, children kept."""
    (tmp_path / "a.txt").write_bytes(b"hello")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "b.txt").write_bytes(b"world")

    key = pds.save(tmp_path)
    loaded = pds.load(key)
    assert isinstance(loaded, Path)
    assert loaded.is_dir()
    assert loaded.name != tmp_path.name           # directory root name is not preserved
    assert (loaded / "a.txt").read_bytes() == b"hello"
    assert (loaded / "sub" / "b.txt").read_bytes() == b"world"


def test_nested_path_inside_dict_is_converted_at_save_and_materialized_at_load(pds, tmp_path):
    """Path nested in a container: outer dict destructured, inner Path materializes to disk on load.

    The motivating composition scenario: DestructuringMixin handles the outer
    structure, PathValueMixin catches the Path via super().save from
    Destructure's recursion and stores it as an opaque DirectoryBlob.
    """
    (tmp_path / "a.txt").write_bytes(b"hello")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "b.txt").write_bytes(b"world")

    wrapper = {"tree": tmp_path, "label": "x"}
    key = pds.save(wrapper)

    # The outer dict went through DestructuringMixin.
    outer = pds.storage[key]
    assert isinstance(outer, DigestedMapping)

    # The inner Path was stored as a verbatim DirectoryBlob (not destructured);
    # the scalar "tree" key itself stays inline (depth 0 < remaining_depth).
    tree_key = outer.items["tree"]
    tree_raw = pds.storage[tree_key]
    assert type(tree_raw) is DirectoryBlob, \
        f"DirectoryBlob should be stored opaquely, got {type(tree_raw).__name__}"

    # On load, the inner Path materializes back to a real filesystem path.
    loaded = pds.load(key)
    assert loaded["label"] == "x"
    assert isinstance(loaded["tree"], Path)
    assert (loaded["tree"] / "a.txt").read_bytes() == b"hello"
    assert (loaded["tree"] / "sub" / "b.txt").read_bytes() == b"world"


def test_directory_path_file_children_stored_at_content_digest(pds, tmp_path):
    """Each file in a saved directory ends up as plain bytes at its content digest."""
    a, b = b"alpha", b"beta"
    (tmp_path / "a").write_bytes(a)
    (tmp_path / "b").write_bytes(b)

    pds.save(tmp_path)
    keys = set(pds.list())
    assert digest(a) in keys
    assert digest(b) in keys


def test_directoryblob_contents_reference_children_by_digest(pds, tmp_path):
    """The DirectoryBlob's ``contents`` maps filename → child content Digest (not inline bytes)."""
    payload = b"shared-bytes"
    (tmp_path / "f.txt").write_bytes(payload)

    key = pds.save(tmp_path)
    raw = pds.storage[key]
    assert isinstance(raw, DirectoryBlob)
    assert raw.contents["f.txt"] == digest(payload)


def test_two_directories_share_file_storage_via_content_addressing(pds, tmp_path):
    """Two distinct directories holding the same file body share its storage entry."""
    payload = b"shared"
    d1 = tmp_path / "d1"; d1.mkdir(); (d1 / "x").write_bytes(payload)
    d2 = tmp_path / "d2"; d2.mkdir(); (d2 / "y").write_bytes(payload)

    pds.save(d1)
    keys_after_first = set(pds.list())
    pds.save(d2)
    keys_after_second = set(pds.list())

    # The new directory added its own DirectoryBlob entry but reused the file body.
    new_keys = keys_after_second - keys_after_first
    assert digest(payload) not in new_keys
    assert digest(payload) in keys_after_first


def test_empty_directory_path_roundtrip(pds, tmp_path):
    """Saving an empty directory yields an empty DirectoryBlob and round-trips to an empty dir."""
    key = pds.save(tmp_path)
    raw = pds.storage[key]
    assert type(raw) is DirectoryBlob
    assert raw.contents == {}

    loaded = pds.load(key)
    assert isinstance(loaded, Path)
    assert loaded.is_dir()
    assert list(loaded.iterdir()) == []


# ---------------------------------------------------------------------------
# find_path: does a save of this value reach a Path?
# ---------------------------------------------------------------------------


@dataclass
class _Fields:
    a: object
    b: object = None


_Bundle = namedtuple("_Bundle", ["out", "score"])


class _Opaque:
    """Not a container a destructuring save looks inside."""

    def __init__(self, p):
        self.p = p


def test_find_path_finds_a_bare_path(tmp_path):
    assert find_path(tmp_path) is tmp_path


@pytest.mark.parametrize(
    "wrap",
    [
        pytest.param(lambda p: [0, [p]], id="nested-list"),
        pytest.param(lambda p: (p,), id="tuple"),
        pytest.param(lambda p: {"k": p}, id="dict-value"),
        pytest.param(lambda p: {p: "v"}, id="dict-key"),
        pytest.param(lambda p: _Fields(a=1, b={"deep": [p]}), id="dataclass-field"),
    ],
)
def test_find_path_descends_the_containers_digest_descends(tmp_path, wrap):
    assert find_path(wrap(tmp_path)) is tmp_path


@pytest.mark.parametrize(
    "wrap",
    [
        pytest.param(lambda p: _Bundle(p, 0.5), id="namedtuple"),
        pytest.param(lambda p: {p}, id="set"),
        pytest.param(lambda p: frozenset({p}), id="frozenset"),
        pytest.param(lambda p: [_Bundle(p, 0.5)], id="namedtuple-in-list"),
    ],
)
def test_find_path_descends_containers_destructuring_treats_as_opaque(tmp_path, wrap):
    """The guard must be broader than destructuring, or it lets the bug back in.

    Destructuring stores a namedtuple / set verbatim, but ``digest`` recurses
    into both and *reads the file* — so a path hidden in one still decides the
    key.  A caller that cannot honour path semantics across a machine boundary
    has to see it, or the far side digests the same name against its own
    filesystem and the ``digest(x) == save_value(x)`` seal breaks silently.
    """
    assert find_path(wrap(tmp_path)) is tmp_path


@pytest.mark.parametrize(
    "value",
    [
        pytest.param([1, "two", b"three"], id="scalars"),
        pytest.param({}, id="empty"),
        pytest.param("/not/a/path/just/a/string", id="path-shaped-string"),
    ],
)
def test_find_path_returns_none_without_a_path(value):
    assert find_path(value) is None


def test_find_path_stops_where_digest_stops(tmp_path):
    """A plain object is `Indigestible`, so no path inside it can decide a key.

    This is the boundary: ``find_path`` follows ``digest``, and ``digest``
    cannot see into an arbitrary object either — it raises rather than
    reading the file.  Nothing to warn about, so nothing to report.
    """
    assert find_path(_Opaque(tmp_path)) is None
    with pytest.raises(Indigestible):
        digest(_Opaque(tmp_path))


def test_find_path_does_not_consume_a_generator(tmp_path):
    """Walking must not have the side effect of exhausting a one-shot iterable."""
    gen = (x for x in [tmp_path])
    find_path(gen)
    assert list(gen) == [tmp_path]


def test_find_path_terminates_on_a_cycle(tmp_path):
    cyclic = [1]
    cyclic.append(cyclic)
    assert find_path(cyclic) is None
    cyclic.append(tmp_path)
    assert find_path(cyclic) is tmp_path
