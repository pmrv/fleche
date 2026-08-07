import dataclasses
import os
import sys
from collections.abc import Iterable, Mapping
from numbers import Number
from pathlib import Path
from typing import Any
import tempfile
import weakref

from . import base
from .. import _attrs
from .. import digest


def find_path(value: Any) -> Path | None:
    """Return a :class:`~pathlib.Path` :func:`~fleche.digest.digest` would read, if any.

    Stops at the first ``Path`` reachable inside *value*, returning ``None``
    if there is none.  Which one comes back when there are several is
    unspecified: this answers "is there one", and the path itself is there to
    name in the resulting error.

    This is a *predicate helper*, not part of the storage protocol: it exists
    so a caller that cannot honour path semantics (notably
    :class:`fleche.remote.SshCache`, where a path's meaning does not survive
    the hop to another filesystem) can detect the situation up front instead
    of silently storing something else.  Shared cycles are visited once.

    **The walk deliberately mirrors** :func:`~fleche.digest.digest`, **not
    destructuring**, and that difference is the whole point.  Destructuring
    treats namedtuples, sets, and frozensets as opaque, but ``digest``
    recurses into all of them and *reads the file* — so a path hidden in one
    still decides the key.  Locally that is harmless, because the process
    computing the digest is the one holding the file.  Across a machine
    boundary it is not: the far side would digest the same name against its
    own filesystem, which is exactly the ``digest(x) == save_value(x)`` break
    the caller is trying to prevent.  Mirroring destructuring here would let
    ``Bundle(path, 0.5)`` through and reintroduce it.

    Mirroring means mirroring ``digest``'s *containers*, not a list of them:
    the iterable arm below walks anything iterable, as ``digest`` does, and
    skips only what ``digest`` itself never looks inside.  An allowlist of
    concrete types is the same bug in slower motion — it covers ``list`` and
    ``tuple`` and lets a ``deque`` through.
    """
    seen: set[int] = set()
    stack: list[Any] = [value]
    while stack:
        item = stack.pop()
        if isinstance(item, Path):
            return item
        if isinstance(item, (digest.Digest, Number, str, bytes, bytearray)):
            continue
        if id(item) in seen:
            continue
        seen.add(id(item))
        if isinstance(item, Mapping):
            stack.extend(item.keys())
            stack.extend(item.values())
        elif dataclasses.is_dataclass(item) and not isinstance(item, type):
            stack.extend(getattr(item, f.name) for f in dataclasses.fields(item))
        elif _attrs.is_attrs_instance(item):
            stack.extend(v for _, v in _attrs.field_items(item))
        elif isinstance(item, Iterable):
            # ``digest``'s ``Iterable`` arm walks *any* iterable, so this one
            # has to as well: a path in a ``deque`` decides the key exactly as
            # much as one in a list, and an allowlist of concrete types silently
            # stops covering whatever a caller reaches for next.  Three
            # exclusions, each mirroring something ``digest`` does earlier:
            #
            # * :data:`~fleche.digest.OPAQUE_ITERABLES` — matched above the
            #   ``Iterable`` arm, hashing their own buffer without looking at
            #   elements, so no path inside one can reach a digest.
            # * ``range`` — its elements are ``int`` by construction, and
            #   materializing ``range(10**9)`` onto the stack to learn that
            #   would be a denial of service.
            # * one-shot iterators, which are their own ``__iter__``.  Walking
            #   a generator consumes it; ``digest`` has already done so by the
            #   time a value could ship, so there is nothing left in one for us
            #   to find anyway.
            if isinstance(item, (digest.OPAQUE_ITERABLES, range)):
                continue
            try:
                if iter(item) is item:
                    continue
            except TypeError:
                continue
            stack.extend(item)
    return None


class TempPath(type(Path())):  # ty: ignore[unsupported-base]
    """
    A Path that deletes its backing temp tree when no references remain.
    Paths derived via /, .parent, .with_suffix, etc. share the same
    TemporaryDirectory and keep it alive collectively.

    On 3.12+ propagation rides ``with_segments``, the single hook pathlib
    routes every derived path through.  3.11 has no such instance hook — its
    derivation goes through the *classmethods* ``_from_parsed_parts`` /
    ``_from_parts``, which never see the originating instance — so there the
    class keeps a weak registry of live temp roots and re-attaches the
    matching ``TemporaryDirectory`` to any path constructed under one.  The
    registry holds only weak references: instances alone keep a root alive,
    so cleanup semantics are identical on both versions.
    """

    # str(root dir) -> TemporaryDirectory, weakly; used by the 3.11 branch only.
    _live_roots: "weakref.WeakValueDictionary[str, tempfile.TemporaryDirectory]" = (
        weakref.WeakValueDictionary()
    )

    @classmethod
    def mkdtemp(
        cls,
    ) -> "TempPath":
        root = tempfile.TemporaryDirectory(
            suffix="fleche",
            ignore_cleanup_errors=True,
        )
        obj = cls(root.name)
        object.__setattr__(obj, "_temp_root", root)
        if sys.version_info < (3, 12):
            cls._live_roots[str(obj)] = root
        return obj

    if sys.version_info >= (3, 12):

        def with_segments(self, *pathsegments):
            new = super().with_segments(*pathsegments)
            root = getattr(self, "_temp_root", None)
            if root is not None:
                object.__setattr__(new, "_temp_root", root)
            return new

    else:

        @classmethod
        def _adopt_live_root(cls, new: "TempPath") -> "TempPath":
            path_str = str(new)
            for root_str, root in list(cls._live_roots.items()):
                if path_str == root_str or path_str.startswith(root_str + os.sep):
                    object.__setattr__(new, "_temp_root", root)
                    break
            return new

        @classmethod
        def _from_parsed_parts(cls, drv, root, parts):
            return cls._adopt_live_root(super()._from_parsed_parts(drv, root, parts))

        @classmethod
        def _from_parts(cls, args):
            return cls._adopt_live_root(super()._from_parts(args))


class FileBlob:
    """A stored file: a basename paired with a reference to its content.

    A file is identified by *(name, content)*.  The content ``bytes`` are stored
    once under their own content digest — so identical bodies deduplicate across
    names, and even with plain ``bytes`` values — and this small record pairs
    that content reference with the file's basename.  On load it materializes at
    ``<tempdir>/<name>`` so ``.name`` / ``.suffix`` / ``.stem`` are faithful, and
    a downstream consumer receives an ordinary ``Path`` with the right name.

    To store file content *without* a name (content only, maximal reuse), return
    the plain ``bytes`` instead of a ``Path``.

    Plain ``__dict__`` (no ``__slots__``) so H5 can reconstruct it; the
    ``"FileBlob"`` salt in :meth:`__digest__` MUST match ``fleche.digest``'s file
    ``Path`` arm.
    """

    def __init__(self, name, content):
        self.name = name
        self.content = content  # Digest of the file's content bytes

    def __eq__(self, other):
        return isinstance(other, FileBlob) and (self.name, self.content) == (
            other.name,
            other.content,
        )

    __hash__ = None  # mutable; not intended as a dict key

    def __digest__(self):
        return digest.digest(("FileBlob", self.name, self.content))

    def __repr__(self):
        return f"FileBlob({self.name!r}, {self.content!r})"


class DirectoryBlob:
    """A stored directory: ``{name: content_ref}``, keyed by its tree alone.

    A directory's *root* name is **not** part of its identity — directories hash
    by their content (the tree) — but its child names are (they are the dict
    keys).  Each child is a content reference: a file child to its content
    ``bytes``, a subdirectory child to its own :class:`DirectoryBlob`.  A
    reloaded directory is therefore named by its digest, its children by their
    real names.

    Stored verbatim by :class:`~fleche.storage.destructuring.DestructuringMixin`
    (not a dict subclass, not a dataclass, so no match arm catches it).
    Kept as a plain ``__dict__``-backed class (no ``__slots__``): some backends
    reconstruct via ``obj.__dict__.update(state)`` (e.g. bagofholding's H5
    unpacker), which a slots-only object cannot satisfy.
    """

    def __init__(self, contents):
        self.contents = dict(contents)

    def __eq__(self, other):
        return isinstance(other, DirectoryBlob) and self.contents == other.contents

    __hash__ = None  # mutable; not intended as a dict key

    def __digest__(self):
        # Digest a (type_name, payload) tuple — the codebase idiom for custom
        # digests.  The "DirectoryBlob" element salts the hash so this is not
        # digest-equal to a plain dict carrying the same {name: Digest} mapping.
        return digest.digest(("DirectoryBlob", self.contents))

    def __repr__(self):
        return f"DirectoryBlob({self.contents!r})"


class PathValueMixin(base.ValueStorage):
    """Convert :class:`~pathlib.Path` values to blobs (and back).

    A **file** is stored as its content ``bytes`` (deduplicated under the content
    digest) wrapped in a :class:`FileBlob` carrying the basename — so files are
    keyed by *(name, content)* and a cache hit returns a path with its real name.
    A **directory** is stored as a :class:`DirectoryBlob` keyed by its tree only;
    its root name is dropped (a reloaded directory is named by its digest, its
    children by their real names).  Plain ``bytes`` are the way to store file
    content without a name.

    The traversal never goes through ``self.save`` / ``self.load`` — every
    storage call uses ``super()`` — so this mixin composes cleanly with
    :class:`~fleche.storage.destructuring.DestructuringMixin` above it without
    load-context ambiguity.  Compose **below** ``DestructuringMixin`` in the MRO
    so ``super().save`` from Destructure's recursion lands here for nested Paths.
    """

    def save(self, value: Any, key: digest.Digest | None = None) -> digest.Digest:
        if isinstance(value, Path):
            if value.is_file():
                # Content deduplicates as plain bytes; the FileBlob record adds
                # the name (the file's key is digest(name, content)).
                content = super().save(value.read_bytes())
                return super().save(FileBlob(value.name, content), key)
            if value.is_dir():
                return super().save(self._build(value), key)
        return super().save(value, key)

    def _build(self, p: Path) -> DirectoryBlob:
        contents = {}
        for child in sorted(p.iterdir()):
            if child.is_file():
                contents[child.name] = super().save(child.read_bytes())
            elif child.is_dir():
                contents[child.name] = super().save(self._build(child))
        return DirectoryBlob(contents)

    def load(self, key: digest.Digest | str) -> Any:
        value = super().load(key)
        if isinstance(value, FileBlob):
            # Materialize at <tempdir>/<name> so the basename round-trips.
            target = TempPath.mkdtemp() / value.name
            target.write_bytes(super().load(value.content))
            return target
        if isinstance(value, DirectoryBlob):
            # No stored root name — materialize under the digest (mangled root).
            path = TempPath.mkdtemp() / str(key)
            self._materialize(path, value)
            return path
        return value

    def _raw_sub_digests(self, raw: Any) -> set[digest.Digest]:
        """Report the content blobs a stored path record points at.

        Without this a reachability walk sees a :class:`FileBlob` /
        :class:`DirectoryBlob` as a childless leaf, so the ``bytes`` holding
        the actual file content look unreferenced and ``gc`` reclaims them —
        destroying every path-valued entry it sweeps past.  The blobs are
        precisely a *name plus references*, so the references have to be
        declared here, at the layer that creates them.
        """
        if isinstance(raw, FileBlob):
            return {raw.content}
        if isinstance(raw, DirectoryBlob):
            return set(raw.contents.values())
        return super()._raw_sub_digests(raw)

    def _materialize(self, path: Path, blob: DirectoryBlob) -> None:
        path.mkdir()
        for name, child_ref in blob.contents.items():
            child = super().load(child_ref)
            if isinstance(child, DirectoryBlob):
                self._materialize(path / name, child)
            elif isinstance(child, (bytes, bytearray)):
                (path / name).write_bytes(child)
            else:
                raise TypeError(
                    f"directory entry {name!r} resolved to unexpected type "
                    f"{type(child).__name__}"
                )
