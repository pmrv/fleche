import hashlib
import importlib.metadata
import logging
import threading
from abc import ABC, abstractmethod
from collections import Counter
import dataclasses as _dataclasses
import datetime
from dataclasses import dataclass
from numbers import Number
from typing import Any, Callable, Protocol, runtime_checkable

from . import base
from .. import _attrs
from .. import digest

logger = logging.getLogger(__name__)


class Digested(base.ChildItems, ABC):
    @abstractmethod
    def underlying(self):
        """Return plain underlying value, ie. list/dict/etc of nested values or their partial digests"""

    # mess with our hash to ensure that we are referentially transparent with respect to the underlying list.
    # For the replacement of the 'real' list with the 'digested' list to be invisible to caches, they must hash to the
    # same values.
    def __digest__(self):
        return digest.digest(self.underlying())

    @abstractmethod
    def mend(self, storage: 'DestructuringMixin'): ...

    @classmethod
    def sunder(cls, intern: Callable[[Any], tuple[Any, int | float]], value: Any):
        """Recurse into *value*'s children via *intern*, then decide inline-vs-store.

        Shared template for every concrete subclass: enumerate child slots (via
        :meth:`_slots`), intern each one, and either return the rebuilt plain value
        (:meth:`_rebuild_plain`, no child became a Digest back-reference) or a *cls*
        wrapper around the interned children (:meth:`_rebuild_digest`, at least one did).

        A child that is itself a wrapper (inlined because it is shallow, but holding a
        reference further down) counts as a reference too.  That way the wrappers mark
        exactly the path from the entry's root to each reference, plain subtrees stay
        plain, and :meth:`mend` only descends where something needs resolving.
        """
        slots = cls._slots(value)
        if slots is None:
            # opt-out: value resists destructuring, treat as opaque
            return value, float("inf")
        if not slots:
            return value, 0

        labels, raw_children = zip(*slots)
        children, depths = zip(*(intern(v) for v in raw_children))
        depth = 1 + max(depths)

        if not any(isinstance(c, (digest.Digest, Digested)) for c in children):
            return cls._rebuild_plain(value, labels, children), depth
        return cls._rebuild_digest(value, labels, children), depth

    @classmethod
    @abstractmethod
    def _slots(cls, value: Any) -> list[tuple[Any, Any]] | None:
        """Enumerate ``(label, child)`` pairs to recurse into, or ``None`` to opt out."""

    @classmethod
    @abstractmethod
    def _rebuild_plain(cls, value: Any, labels: tuple, children: tuple) -> Any:
        """Rebuild the result when no interned child became a Digest back-reference."""

    @classmethod
    @abstractmethod
    def _rebuild_digest(cls, value: Any, labels: tuple, children: tuple) -> Any:
        """Build the *cls* wrapper when some interned child became a Digest back-reference."""

    @staticmethod
    def get(storage, key):
        if isinstance(key, digest.Digest):
            return storage.load(key)
        if isinstance(key, Digested):
            return key.mend(storage)
        return key

@dataclass
class DigestedIterable(Digested):
    items: list | tuple

    def __hash__(self):
        # Forward the hash of the underlying container: if it was a dict key (a
        # tuple), the wrapper inlined in its place must be a valid key as well.
        return hash((type(self), self.items))

    def underlying(self):
        return self.items

    def child_items(self) -> list[tuple[None, Any]]:
        return [(None, v) for v in self.items]

    def mend(self, storage: 'DestructuringMixin') -> list | tuple:
        return type(self.items)(map(lambda v: self.get(storage, v), self.items))

    @classmethod
    def _slots(cls, value: list | tuple) -> list[tuple[None, Any]]:
        return [(None, v) for v in value]

    @classmethod
    def _rebuild_plain(cls, value: list | tuple, labels: tuple, children: tuple) -> list | tuple:
        return type(value)(children)

    @classmethod
    def _rebuild_digest(cls, value: list | tuple, labels: tuple, children: tuple) -> 'DigestedIterable':
        return cls(type(value)(children))


@dataclass
class DigestedDict(Digested):
    items: dict

    def underlying(self):
        return self.items

    def child_items(self) -> list[tuple[None, Any]]:
        # Keys are children too: a key big enough to be written out separately
        # comes back as a Digest, and a sweep that only walked values would
        # reclaim it.  Flat, like the ``_slots`` a save reads — ``mend`` re-pairs.
        return [(None, k) for k in self.items] + [(None, v) for v in self.items.values()]

    def mend(self, storage: 'DestructuringMixin') -> dict:
        return {self.get(storage, k): self.get(storage, v)
                    for k, v in self.items.items()}

    @classmethod
    def _slots(cls, value: dict) -> list[tuple[None, Any]]:
        # keys and values interned as one flat sequence; _rebuild_* re-pairs them by
        # position using len(value) as the key/value split point.
        return [(None, k) for k in value] + [(None, v) for v in value.values()]

    @classmethod
    def _rebuild_plain(cls, value: dict, labels: tuple, children: tuple) -> dict:
        n = len(value)
        return dict(zip(children[:n], children[n:]))

    @classmethod
    def _rebuild_digest(cls, value: dict, labels: tuple, children: tuple) -> 'DigestedDict':
        return cls(cls._rebuild_plain(value, labels, children))


@dataclass
class DigestedFields(Digested):
    """Common base for record-shaped value markers (dataclasses, attrs).

    Subclasses provide :meth:`_field_items` to enumerate ``(name, value)`` pairs from a
    live instance; :meth:`~fleche.storage.destructuring.Digested.sunder`, :meth:`~fleche.storage.destructuring.Digested.mend`, and :meth:`__digest__` are shared.
    Field values may be replaced by :class:`~fleche.digest.Digest` back-references when
    they are stored independently.  :meth:`~fleche.storage.destructuring.Digested.mend` reconstructs the original instance by
    bypassing ``__init__`` / ``__post_init__``, so ``InitVar`` and ``init=False`` fields
    (and attrs slots / frozen instances) are all handled uniformly.
    """

    cls: type
    fields: dict  # {field_name: field_value_or_digest}

    def underlying(self):
        return self.fields

    def __digest__(self):
        # Reproduce the same hash that digest._digest computes for a plain instance:
        # SHA256(cls.__name__ + digest(fields_as_dict)).  Digest values in self.fields are
        # transparent (digest(Digest("abc")) == "abc") so they round-trip correctly.
        m = hashlib.sha256()
        m.update(self.cls.__name__.encode())
        m.update(digest.digest(self.fields).encode())
        return digest.Digest(m.hexdigest())

    def child_items(self) -> list[tuple[str, Any]]:
        # The wrapper stores the ``{name: value}`` field dict rather than an
        # instance, so ``_field_items`` cannot read it back — the dict is the slots.
        return list(self.fields.items())

    def mend(self, storage: 'DestructuringMixin'):
        obj = object.__new__(self.cls)
        for name, val_or_digest in self.fields.items():
            object.__setattr__(obj, name, self.get(storage, val_or_digest))
        return obj

    @staticmethod
    @abstractmethod
    def _field_items(value: Any) -> list[tuple[str, Any]]: ...

    @classmethod
    def _slots(cls, value: Any) -> list[tuple[str, Any]] | None:
        try:
            return cls._field_items(value)
        except (AttributeError, TypeError):
            return None

    @classmethod
    def _rebuild_plain(cls, value: Any, labels: tuple, children: tuple) -> Any:
        # no field was replaced by a Digest -> value is already the right result,
        # unlike DigestedIterable/DigestedDict there is no plain container to rebuild into
        return value

    @classmethod
    def _rebuild_digest(cls, value: Any, labels: tuple, children: tuple) -> 'DigestedFields':
        return cls(type(value), dict(zip(labels, children)))


@dataclass
class DigestedDataclass(DigestedFields):
    """Per-field marker for stdlib :mod:`dataclasses` instances."""

    @staticmethod
    def _field_items(value: Any) -> list[tuple[str, Any]]:
        return [(f.name, getattr(value, f.name)) for f in _dataclasses.fields(value)]


@dataclass
class DigestedAttrs(DigestedFields):
    """Per-field marker for ``attrs``-decorated instances."""

    @staticmethod
    def _field_items(value: Any) -> list[tuple[str, Any]]:
        return _attrs.field_items(value)


_DESTRUCTURERS: list[tuple[Callable[[Any], bool], Callable]] = [
    (lambda v: isinstance(v, (list, tuple)), DigestedIterable.sunder),
    (lambda v: isinstance(v, dict), DigestedDict.sunder),
    (lambda v: _dataclasses.is_dataclass(v) and not isinstance(v, type), DigestedDataclass.sunder),
    (_attrs.is_attrs_instance, DigestedAttrs.sunder),
]


def register_destructurer(pred: Callable[[Any], bool], fn: Callable) -> None:
    """Register a custom container destructurer.

    *pred(value)* should return ``True`` for values this destructurer handles.
    *fn* must accept ``(intern, value)`` where *intern* is
    :meth:`DestructuringMixin._intern_rec`.  Entries are appended after the
    built-in ones; first match wins, so registering a handler for an entirely
    new container type is safe without displacing list/dict/dataclass/attrs.
    Call before any :class:`DestructuringMixin` instance is used.

    A package should instead list its ``(pred, fn)`` pairs under the ``fleche``
    entry point ``destructure``; they are registered before the first save.
    """
    _DESTRUCTURERS.append((pred, fn))


_ENTRY_POINTS_LOADED = False
_ENTRY_POINTS_LOCK = threading.Lock()


def _load_entry_points() -> None:
    """Register the destructurers packages declare under the ``fleche`` entry point ``destructure``.

    Each entry point names a list of ``(pred, fn)`` pairs for
    :func:`register_destructurer`.  Runs once, before the first save of any
    destructuring store, so how a value is split never depends on what the
    process happened to import before.
    """
    global _ENTRY_POINTS_LOADED
    if _ENTRY_POINTS_LOADED:
        return
    with _ENTRY_POINTS_LOCK:
        if _ENTRY_POINTS_LOADED:
            return
        for ep in importlib.metadata.entry_points(group="fleche", name="destructure"):
            try:
                for pred, fn in ep.load():
                    register_destructurer(pred, fn)
            except Exception as e:
                logger.error("Failed to load entry point %s: %s", ep.value, e, exc_info=True)
        _ENTRY_POINTS_LOADED = True


# Leaves that are atomic values rather than containers or opaque objects: depth 0,
# so they inline into their parent like ints do.  Anything else that no
# destructurer claims is opaque (depth ∞) and always gets an entry of its own.
_SCALAR_TYPES = (
    Number,
    str,
    bytes,
    type(None),
    datetime.date,  # datetime.datetime too, and pd.Timestamp
    datetime.time,
    datetime.timedelta,  # pd.Timedelta too
    datetime.tzinfo,
)

# Third-party scalars matched by (top-level module, class name) along the MRO, the
# way digest._SISTER_PACKAGES does, so fleche never imports numpy or pandas.
# np.bool_ is not a numbers.Number since numpy 1.20; the other numpy number
# scalars are, and np.str_/np.bytes_ subclass str/bytes.
_FOREIGN_SCALARS = {
    ("numpy", "bool"),  # np.bool_ on numpy 2
    ("numpy", "bool_"),  # np.bool_ on numpy 1
    ("pandas", "NAType"),
}

# Per-type answers for the _FOREIGN_SCALARS MRO walk.
_FOREIGN_SCALAR_CACHE: dict[type, bool] = {}


def _is_scalar(value: Any) -> bool:
    """Whether *value* is an atomic leaf, inlined like an ``int`` (depth 0)."""
    if isinstance(value, _SCALAR_TYPES):
        return True
    t = type(value)
    try:
        return _FOREIGN_SCALAR_CACHE[t]
    except KeyError:
        pass
    result = any(
        (c.__module__.partition(".")[0], c.__qualname__) in _FOREIGN_SCALARS
        for c in t.__mro__
    )
    _FOREIGN_SCALAR_CACHE[t] = result
    return result


@runtime_checkable
class HasChildDigests(Protocol):
    """Structural protocol for value storages that expose a reference-graph edge query.

    Any :class:`~fleche.storage.base.ValueStorage` that implements
    :meth:`child_digests` satisfies this protocol automatically — no explicit
    registration or inheritance required.  Use ``isinstance(storage, HasChildDigests)``
    to check at runtime whether the storage supports transitive reachability walks.
    """

    def child_digests(self, key: digest.Digest) -> set[digest.Digest]:
        """Return the set of digests directly referenced by the entry at *key*.

        Raises:
            KeyError: if *key* is not present in the storage.
        """
        ...


@dataclass(frozen=True)
class DestructuringMixin(base.ValueStorage):
    """Mixin that recursively destructures collections on save/load.

    Place before a :class:`~fleche.storage.base.ValueMixin` in the MRO to add destructuring
    behavior.  Lists, tuples, and dicts are broken apart so each element is
    stored independently; on load the original structure is reassembled.

    Example:

        >>> from fleche.storage.base import ValueMixin
        >>> from fleche.storage.memory import MemoryBackend
        >>> @dataclass(frozen=True)
        ... class MyValueStorage(DestructuringMixin, ValueMixin, MemoryBackend):
        ...     __hash__ = object.__hash__
        >>> vm = MyValueStorage(storage={})
        >>> key = vm.save([1, [2, 3]])
        >>> vm.load(key) == [1, [2, 3]]
        True
    """

    remaining_depth: int = 1

    @staticmethod
    def _is_trojan_tuple(value):
        return hasattr(value, "_fields") and hasattr(value, "_field_defaults")

    def _intern_rec(self, value: Any, key: digest.Digest | None = None) -> tuple[Any, int | float]:
        """Post-order traversal: recurse to leaves, decide inline-vs-store on the way back up.

        Returns ``(result, depth)`` where *result* is the plain value when ``depth < remaining_depth``
        (the element is inlined in its parent's :class:`~fleche.storage.destructuring.Digested` wrapper) or a :class:`~fleche.digest.Digest` when
        the element was written to storage separately.  Every node in the structure is visited exactly
        once (O(n)), unlike a separate depth-counting pass.
        """
        if isinstance(value, digest.Digest):
            return value, -1

        depth = float("inf")

        if _is_scalar(value):
            depth = 0
        elif isinstance(value, (dict, list, tuple)) and not value:
            # empty containers treated like scalars; no point destructuring nothing
            depth = 0
        elif isinstance(value, tuple) and self._is_trojan_tuple(value):
            # namedtuples break LSP by not accepting a single iterable — treat as opaque scalar
            pass
        else:
            for pred, sunder_fn in _DESTRUCTURERS:
                if pred(value):
                    value, depth = sunder_fn(self._intern_rec, value)
                    break

        if depth < self.remaining_depth:
            return value, depth
        return super().save(value, key), depth

    def save(self, value: Any, key: digest.Digest | None = None) -> digest.Digest:
        _load_entry_points()
        # The top-level value always gets an entry, so whatever its depth, store
        # what its destructurer makes of it.  Calling the destructurer directly
        # skips _intern_rec's second scan of _DESTRUCTURERS.
        if isinstance(value, (list, tuple, dict)) and not value:
            pass  # nothing to destructure
        elif not (isinstance(value, tuple) and self._is_trojan_tuple(value)):
            for pred, sunder_fn in _DESTRUCTURERS:
                if pred(value):
                    value, _ = sunder_fn(self._intern_rec, value)
                    break
        return super().save(value, key)

    def load(self, key: digest.Digest | str) -> Any:
        value = super().load(key)

        match value:
            case Digested():
                return value.mend(self)
            case _:
                return value

    def child_digests(self, key: digest.Digest | str) -> set[digest.Digest]:
        """Direct digest children of the raw entry stored at *key*.

        Bypasses :meth:`~fleche.storage.destructuring.Digested.mend`, so destructured sub-references are returned as
        opaque :class:`~fleche.digest.Digest` keys rather than being followed.
        Intended for reference-graph traversals (GC, debugging) where loading
        the mended value would flatten the structure we need to inspect.

        Raises:
            KeyError: if *key* is not present in the underlying backend.
        """
        return self._raw_sub_digests(super().load(key))

    def count_reuses(self) -> Counter[digest.Digest]:
        """Return a counter of how many times each stored key is referenced as a sub-component.

        Scans every raw entry and tallies the ``Digest`` back-references each
        record declares through :class:`~fleche.storage.base.ChildItems` — every
        wrapper type, built in or registered, on equal footing.  A count of ``0``
        means the key is not pointed to by any other stored value (i.e. a top-level entry).
        A count greater than ``1`` indicates a sub-value shared between multiple parent containers.

        Returns:
            A :class:`~collections.Counter` mapping each :class:`~fleche.digest.Digest` key
            to the number of times it is referenced by other stored entries.

        Example:

            >>> from fleche.storage.memory import ValueMemory
            >>> ds = ValueMemory(storage={})
            >>> shared = [2, 3]
            >>> _ = ds.save([1, shared])
            >>> _ = ds.save([4, shared])
            >>> hits = ds.count_reuses()
            >>> hits[ds.save(shared)]  # [2, 3] is referenced by both outer lists
            2
        """
        counts: Counter[digest.Digest] = Counter({key: 0 for key in self.list()})
        for key in list(counts):
            for sub in self._raw_sub_digests(super().load(key)):
                if sub in counts:
                    counts[sub] += 1
        return counts
