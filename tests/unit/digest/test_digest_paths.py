"""Coverage for the ``Path`` arm in ``fleche.digest._digest_bytes``.

Files digest on ``(basename, content)``; directories digest on their tree alone
(a directory's own root name is not part of its identity).
"""
from pathlib import Path

import pytest

from fleche.digest import digest, Indigestible


# ---- Non-existent paths ----


def test_nonexistent_path_raises_indigestible(tmp_path):
    """A Path that doesn't exist on disk cannot be digested."""
    missing = tmp_path / "does-not-exist"
    with pytest.raises(Indigestible):
        digest(missing)


# ---- File paths ----


def test_file_path_digest_is_name_plus_content(tmp_path):
    """A file Path digests on (basename, content), mirroring the stored FileBlob record.

    ``digest(path) == digest(FileBlob(name, digest(bytes)))`` — the
    ``digest(path) == values.save(path)`` invariant cached lookups rely on — and
    ``!= digest(bytes)`` so a file is distinct from a bare bytes value of the
    same content (while still deduplicating its content blob; see storage tests).
    """
    from fleche.storage.paths import FileBlob

    p = tmp_path / "f.txt"
    p.write_bytes(b"hello world")
    assert digest(p) == digest(FileBlob("f.txt", digest(b"hello world")))
    assert digest(p) != digest(b"hello world")


def test_file_path_digest_changes_with_contents(tmp_path):
    """Different file bodies → different digests."""
    p = tmp_path / "f.txt"
    p.write_bytes(b"alpha")
    d1 = digest(p)
    p.write_bytes(b"beta")
    d2 = digest(p)
    assert d1 != d2


def test_file_path_digest_depends_on_filename(tmp_path):
    """Files are keyed on (name, content): same body, different names → different digests.

    Same basename + same content → identical, regardless of the parent directory.
    """
    a = tmp_path / "a.txt"
    b = tmp_path / "b.txt"
    a.write_bytes(b"same")
    b.write_bytes(b"same")
    assert digest(a) != digest(b)            # name is part of a file's identity

    other = tmp_path / "sub"
    other.mkdir()
    c = other / "a.txt"
    c.write_bytes(b"same")
    assert digest(c) == digest(a)            # same basename + content -> same digest


# ---- Directory paths ----


def test_empty_directory_can_be_digested(tmp_path):
    """An empty directory is digestible (does not raise)."""
    digest(tmp_path)  # smoke


def test_directory_digest_ignores_root_name(tmp_path):
    """A directory hashes by its tree alone — its own root name does not matter."""
    d1 = tmp_path / "alpha"
    d2 = tmp_path / "beta"
    for d in (d1, d2):
        d.mkdir()
        (d / "x.txt").write_bytes(b"X")
        (d / "sub").mkdir()
        (d / "sub" / "y.bin").write_bytes(b"Y")
    assert digest(d1) == digest(d2)          # different root names, identical trees


def test_directory_digest_changes_with_filename(tmp_path):
    """The directory arm hashes ``{name: child}``, so renaming a file changes the digest."""
    (tmp_path / "a.txt").write_bytes(b"x")
    d1 = digest(tmp_path)

    # Rename and re-hash.
    (tmp_path / "a.txt").rename(tmp_path / "b.txt")
    d2 = digest(tmp_path)
    assert d1 != d2


def test_directory_digest_changes_with_file_contents(tmp_path):
    """Mutating a child file changes the directory digest."""
    f = tmp_path / "f.txt"
    f.write_bytes(b"v1")
    d1 = digest(tmp_path)
    f.write_bytes(b"v2")
    d2 = digest(tmp_path)
    assert d1 != d2


def test_directory_digest_stable_across_iteration_order(tmp_path):
    """Two directories with the same {name: bytes} payload share a digest.

    ``_digest_mapping`` sorts by key-digest, so filesystem ``iterdir`` order
    must not leak into the result.
    """
    d1 = tmp_path / "d1"
    d2 = tmp_path / "d2"
    d1.mkdir()
    d2.mkdir()
    # Write children in different orders.
    (d1 / "a").write_bytes(b"A")
    (d1 / "b").write_bytes(b"B")
    (d2 / "b").write_bytes(b"B")
    (d2 / "a").write_bytes(b"A")
    assert digest(d1) == digest(d2)


def test_nested_directory_digest_recurses(tmp_path):
    """Mutating a deeply nested file changes the root directory digest."""
    sub = tmp_path / "sub" / "deeper"
    sub.mkdir(parents=True)
    leaf = sub / "leaf.txt"
    leaf.write_bytes(b"v1")
    d1 = digest(tmp_path)
    leaf.write_bytes(b"v2")
    d2 = digest(tmp_path)
    assert d1 != d2


def test_directory_digest_differs_from_plain_dict(tmp_path):
    """A directory digest does not collide with a plain dict of {name: path}.

    A directory hashes as the tuple ``("DirectoryBlob", {name: child_digest})``,
    whereas a plain dict hashes as a bare mapping — different shapes and salts,
    so they differ even though both ultimately reference the same child content.
    """
    (tmp_path / "a.txt").write_bytes(b"hello")
    plain = {"a.txt": tmp_path / "a.txt"}
    assert digest(tmp_path) != digest(plain)


# ---- Non-file, non-directory paths ----


def test_special_path_raises_indigestible(tmp_path):
    """A path that exists but is neither a regular file nor a directory raises.

    GUESS: covers the ``else`` branch (e.g. symlinks to nowhere, sockets,
    FIFOs).  A dangling symlink is the most portable trigger: ``exists()``
    returns False for it (so we'd land in the not-exists branch first).  Use a
    FIFO instead — POSIX only, skip elsewhere.
    """
    import os
    fifo = tmp_path / "fifo"
    try:
        os.mkfifo(fifo)
    except (AttributeError, NotImplementedError, OSError):
        pytest.skip("FIFOs not supported on this platform")
    with pytest.raises(Indigestible):
        digest(fifo)
