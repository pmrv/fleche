import hashlib
from abc import ABC, abstractmethod
from collections import Counter
import dataclasses as _dataclasses
from dataclasses import dataclass
from numbers import Number
from typing import Any, Callable

from . import base
from .. import digest


class Digested(ABC):
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
    @abstractmethod
    def sunder(cls, intern: Callable[[Any], tuple[Any, int | float]], value: Any): ...

    @staticmethod
    def get(storage, key):
        if isinstance(key, digest.Digest):
            return storage.get(key)
        else:
            return key

@dataclass
class DigestedIterable(Digested):
    items: list | tuple

    def underlying(self):
        return self.items

    def mend(self, storage: 'DestructuringMixin') -> list | tuple:
        return type(self.items)(map(lambda v: self.get(storage, v), self.items))

    @classmethod
    def sunder(cls, intern: Callable[[Any], tuple[Any, int | float]], value: list | tuple):
        children, depths = zip(*(intern(v) for v in value))
        depth = 1 + max(depths)
        items = type(value)(children)
        if all(not isinstance(r, digest.Digest) for r in items):
            # intern did do anything to our children because we're out of depth, return them verbatim
            return items, depth
        return cls(items), depth


@dataclass
class DigestedDict(Digested):
    items: dict

    def underlying(self):
        return self.items

    def mend(self, storage: 'DestructuringMixin') -> dict:
        return {self.get(storage, k): self.get(storage, v)
                    for k, v in self.items.items()}

    @classmethod
    def sunder(cls, intern: Callable[[Any], tuple[Any, int | float]], value: dict):
        kk, k_depths = zip(*(intern(k) for k in value))
        vv, v_depths = zip(*(intern(v) for v in value.values()))
        depth = 1 + max(max(k_depths), max(v_depths))
        items = dict(zip(kk, vv))
        if all(not isinstance(r, digest.Digest) for r in (*items.keys(), *items.values())):
            # intern did not do anything to our children because we're out of depth, return them verbatim
            return items, depth
        return cls(items), depth


@dataclass
class DigestedDataclass(Digested):
    """Digested wrapper for dataclass instances, storing field values separately in CAS.

    Field values may be replaced by :class:`~fleche.digest.Digest` back-references when they are
    stored independently.  :meth:`mend` reconstructs the original instance by bypassing
    ``__init__`` / ``__post_init__``, so ``InitVar`` and ``init=False`` fields are all handled
    uniformly: we restore whatever attribute values were present at sunder time.
    """

    cls: type
    fields: dict  # {field_name: field_value_or_digest}

    def underlying(self):
        return self.fields

    def __digest__(self):
        # Reproduce the same hash that digest._digest computes for a plain dataclass instance:
        # SHA256(cls.__name__ + digest(fields_as_dict)).  Digest values in self.fields are
        # transparent (digest(Digest("abc")) == "abc") so they round-trip correctly.
        m = hashlib.sha256()
        m.update(self.cls.__name__.encode())
        m.update(digest.digest(self.fields).encode())
        return digest.Digest(m.hexdigest())

    def mend(self, storage: 'DestructuringMixin'):
        obj = object.__new__(self.cls)
        for name, val_or_digest in self.fields.items():
            object.__setattr__(obj, name, self.get(storage, val_or_digest))
        return obj

    @classmethod
    def sunder(cls, intern: Callable[[Any], tuple[Any, int | float]], value: Any):
        # Fall back to whole-object storage on any structural problem.
        try:
            dc_fields = _dataclasses.fields(value)
        except TypeError:
            return value, float("inf")

        if not dc_fields:
            return value, 0

        try:
            field_values = [getattr(value, f.name) for f in dc_fields]
        except AttributeError:
            return value, float("inf")

        children, depths = zip(*(intern(v) for v in field_values))
        depth = 1 + max(depths)

        if all(not isinstance(c, digest.Digest) for c in children):
            return value, depth

        fields = dict(zip((f.name for f in dc_fields), children))
        return cls(type(value), fields), depth


@dataclass(frozen=True)
class DestructuringMixin(base.StorageBackend):
    """Mixin that recursively destructures collections on save/load.

    Place before a concrete :class:`StorageBackend` in the MRO to add
    destructuring behavior.  Lists, tuples, and dicts are broken apart so each
    element is stored independently; on load the original structure is
    reassembled.

    Example:

        >>> from fleche.storage.base import ValueMixin
        >>> from fleche.storage.memory import MemoryBackend
        >>> @dataclass(frozen=True)
        ... class MyValueStorage(ValueMixin, DestructuringMixin, MemoryBackend): ...
        >>> vm = MyValueStorage(storage={})
        >>> key = vm.save([1, [2, 3]])
        >>> vm.load(key) == [1, [2, 3]]
        True
    """

    remaining_depth: int = 0

    @staticmethod
    def _is_trojan_tuple(value):
        return hasattr(value, "_fields") and hasattr(value, "_field_defaults")

    def _intern_rec(self, value: Any, key: digest.Digest | None = None) -> tuple[Any, int | float]:
        """Post-order traversal: recurse to leaves, decide inline-vs-store on the way back up.

        Returns ``(result, depth)`` where *result* is the plain value when ``depth < remaining_depth``
        (the element is inlined in its parent's :class:`Digested` wrapper) or a :class:`Digest` when
        the element was written to storage separately.  Every node in the structure is visited exactly
        once (O(n)), unlike a separate depth-counting pass.
        """
        if isinstance(value, digest.Digest):
            return value, -1

        depth = float("inf")
        match value:
            case Number() | str() | bytes():
                depth = 0

            # treat exactly like scalars, but guard syntax gets a bit weird if we try to join
            # technically this violates our recursion of 1 + max children depth, but I just can't see a use for
            # destructuring the empty container
            case dict() | list() | tuple() if not value:
                depth = 0

            # because nothing is ever simple, namedtuple break LSP by not accepting a single iterable
            # this is considered highly annoying, because e.g. a lot of numpy functions we'd like to wrap return
            # NamedTuple
            case tuple() if self._is_trojan_tuple(value):
                pass

            case list() | tuple():
                value, depth = DigestedIterable.sunder(self._intern_rec, value)

            case dict():
                value, depth = DigestedDict.sunder(self._intern_rec, value)

            case _ if _dataclasses.is_dataclass(value) and not isinstance(value, type):
                value, depth = DigestedDataclass.sunder(self._intern_rec, value)

        if depth < self.remaining_depth:
            return value, depth
        return super().put(value, key or digest.digest(value)), depth

    def put(self, value: Any, key: digest.Digest) -> digest.Digest:

        match value:
            case list() | tuple() | dict() if not value:
                return super().put(value, key)

            case list() | tuple() | dict():
                value_or_digest, depth = self._intern_rec(value, key)
                # if given value is nominally not deep enough to be destructured/saved during recursion
                # we do it here manually as the recursion base case
                if depth < self.remaining_depth:
                    return super().put(value_or_digest, key)
                else:
                    return value_or_digest

            case _ if _dataclasses.is_dataclass(value) and not isinstance(value, type):
                if not _dataclasses.fields(value):
                    return super().put(value, key)
                value_or_digest, depth = self._intern_rec(value, key)
                if depth < self.remaining_depth:
                    return super().put(value_or_digest, key)
                else:
                    return value_or_digest

            case _:
                return super().put(value, key)

    def get(self, key: digest.Digest | Any) -> Any:
        value = super().get(key)

        match value:
            case Digested():
                return value.mend(self)
            case _:
                return value

    def count_reuses(self) -> Counter[digest.Digest]:
        """Return a counter of how many times each stored key is referenced as a sub-component.

        Scans every raw entry and tallies ``Digest`` back-references found inside
        :class:`DigestedIterable` and :class:`DigestedDict` wrappers.  A count of ``0``
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
            raw = super().get(key)
            match raw:
                case DigestedIterable():
                    for item in raw.items:
                        if isinstance(item, digest.Digest) and item in counts:
                            counts[item] += 1
                case DigestedDict():
                    for k, v in raw.items.items():
                        if isinstance(k, digest.Digest) and k in counts:
                            counts[k] += 1
                        if isinstance(v, digest.Digest) and v in counts:
                            counts[v] += 1
                case DigestedDataclass():
                    for v in raw.fields.values():
                        if isinstance(v, digest.Digest) and v in counts:
                            counts[v] += 1
        return counts
