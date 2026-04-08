import logging
from dataclasses import dataclass
from numbers import Number

from abc import ABC, abstractmethod
from typing import Iterable, Any, Callable

from ..digest import digest, Digest, DIGEST_LENGTH
from ..call import Call, QueryCall

logger = logging.getLogger("fleche.storage")


class SaveError(Exception):
    pass


class AmbiguousDigestError(ValueError):
    pass


class StorageBackend(ABC):
    """Primitive backend interface for key-value storage.

    Backends implement the low-level ``put``/``get``/``pop``/``list``
    operations.  Higher-level classes (:class:`ValueMixin`, :class:`CallMixin`)
    add domain-specific logic on top.
    """

    # Primitive operations necessary to implement in new backends

    @abstractmethod
    def list(self) -> Iterable[Digest]: ...

    @abstractmethod
    def put(self, value: Any, key: Digest) -> Digest: ...

    @abstractmethod
    def get(self, key: Digest) -> Any: ...

    @abstractmethod
    def _evict(self, key: Digest) -> None: ...

    def _contains(self, key: Digest) -> bool:
        try:
            self.get(key)
            return True
        except KeyError:
            return False

    # public API on top

    def evict(self, key: Digest | str) -> None:
        """Removes the entry corresponding to the key from the storage."""
        if len(key) < DIGEST_LENGTH:
            key = self.expand(key)
        else:
            key = Digest(key)
        self._evict(key)

    def contains(self, key: Digest | str) -> bool:
        if len(key) < DIGEST_LENGTH:
            try:
                key = self.expand(key)
            except KeyError:
                return False
        else:
            key = Digest(key)
        return self._contains(key)

    def expand(self, key: Digest | str) -> Digest:
        """Expands a short-hand digest to the full length one."""
        if len(key) >= DIGEST_LENGTH:
            return Digest(str(key))
        if len(key) < 4:
            raise KeyError(key)

        matches = sorted([k for k in self.list() if k.startswith(key)])
        if not matches:
            raise KeyError(key)
        if len(matches) > 1:
            # find longest common prefix of the first two matches to find where they diverge
            m1, m2 = matches[0], matches[1]
            for i, (c1, c2) in enumerate(zip(m1, m2)):
                if c1 != c2:
                    break
            else:
                i = min(len(m1), len(m2))

            raise AmbiguousDigestError(
                f"Short digest {key} is ambiguous; need at least {i+1} characters."
            )
        return Digest(matches[0])

    def shrink(self, key: Digest | str) -> Digest:
        """Find the shortest substring that is still an unambigious reference to the same value."""
        for ln in range(4, len(key)):
            try:
                self.expand(key[:ln])
                return Digest(key[:ln])
            except AmbiguousDigestError:
                continue
        raise AmbiguousDigestError(
            f"Digest {key} cannot be shrunk without becoming ambigious!"
        )


class ValueStorage(StorageBackend):
    """Abstract domain interface for value storage."""

    @abstractmethod
    def save(self, value: Any, key: Digest | None = None) -> Digest: ...

    @abstractmethod
    def load(self, key: Digest | str) -> Any: ...


class ValueMixin(ValueStorage, StorageBackend):
    """Bridges :class:`ValueStorage` with :class:`StorageBackend` primitives.

    Implements ``save`` and ``load`` using ``put`` and ``get``.
    Concrete classes inherit from this and a :class:`StorageBackend`
    implementation to get a fully functional value storage.
    """

    def save(self, value: Any, key: Digest | None = None) -> Digest:
        if key is None:
            key = digest(value)
        logger.debug("Saving value with key %s", key)
        return self.put(value, key)

    def load(self, key: Digest | str) -> Any:
        if len(key) < DIGEST_LENGTH:
            key = self.expand(key)
        else:
            key = Digest(key)
        logger.debug("Loading value with key %s", key)
        return self.get(key)


class Digested(ABC):
    @abstractmethod
    def underlying(self):
        """Return plain underlying value, ie. list/dict/etc of nested values or their partial digests"""

    # mess with our hash to ensure that we are referentially transparent with respect to the underlying list.
    # For the replacement of the 'real' list with the 'digested' list to be invisible to caches, they must hash to the
    # same values.
    def __digest__(self):
        return digest(self.underlying())

    @abstractmethod
    def mend(self, storage: 'DestructuringMixin'): ...

    @classmethod
    @abstractmethod
    def sunder(cls, intern: Callable[[Any], tuple[Any, int | float]], value: Any): ...


@dataclass
class DigestedIterable(Digested):
    items: list | tuple

    def underlying(self):
        return self.items

    def mend(self, storage: 'DestructuringMixin') -> list | tuple:
        return type(self.items)(map(storage.get, self.items))

    @classmethod
    def sunder(cls, intern: Callable[[Any], tuple[Any, int | float]], value: list | tuple):
        children, depths = zip(*(intern(v) for v in value))
        depth = 1 + max(depths)
        items = type(value)(children)
        if all(not isinstance(r, Digest) for r in items):
            # intern did do anything to our children because we're out of depth, return them verbatim
            return items, depth
        return cls(items), depth


@dataclass
class DigestedDict(Digested):
    items: dict

    def underlying(self):
        return self.items

    def mend(self, storage: 'DestructuringMixin') -> dict:
        return {storage.get(k): storage.get(v) for k, v in self.items.items()}

    @classmethod
    def sunder(cls, intern: Callable[[Any], tuple[Any, int | float]], value: dict):
        kk, k_depths = zip(*(intern(k) for k in value))
        vv, v_depths = zip(*(intern(v) for v in value.values()))
        depth = 1 + max(max(k_depths), max(v_depths))
        items = dict(zip(kk, vv))
        if all(not isinstance(r, Digest) for r in (*items.keys(), *items.values())):
            # intern did do anything to our children because we're out of depth, return them verbatim
            return items, depth
        return cls(items), depth


class DestructuringMixin(StorageBackend):
    """Mixin that recursively destructures collections on save/load.

    Place before a concrete :class:`StorageBackend` in the MRO to add
    destructuring behavior.  Lists, tuples, and dicts are broken apart so each
    element is stored independently; on load the original structure is
    reassembled.

    Example::

        class DestructuringMemory(ValueMixin, DestructuringMixin, Memory):
            pass

        dm = DestructuringMemory(storage={})
        key = dm.save([1, [2, 3]])
        assert dm.load(key) == [1, [2, 3]]
    """

    remaining_depth: int = 0

    def _intern_rec(self, value: Any) -> tuple[Any, int | float]:
        """Post-order traversal: recurse to leaves, decide inline-vs-store on the way back up.

        Returns ``(result, depth)`` where *result* is the plain value when ``depth < remaining_depth``
        (the element is inlined in its parent's :class:`Digested` wrapper) or a :class:`Digest` when
        the element was written to storage separately.  Every node in the structure is visited exactly
        once (O(n)), unlike a separate depth-counting pass.
        """
        depth = float("inf")
        match value:
            case Number() | str() | bytes():
                depth = 0

            # treat exactly like scalars, but guard syntax gets a bit weird if we try to join
            # technically this violates our recursion of 1 + max children depth, but I just can't see a use for
            # destructuring the empty container
            case dict() | list() | tuple() if not value:
                depth = 0

            case list() | tuple():
                value, depth = DigestedIterable.sunder(self._intern_rec, value)

            case dict():
                value, depth = DigestedDict.sunder(self._intern_rec, value)

        if depth < self.remaining_depth:
            return value, depth
        return super().put(value, digest(value)), depth

    def put(self, value: Any, key: Digest) -> Digest:
        if isinstance(value, Digest):
            return value

        match value:
            case list() | tuple() if not value:
                return super().put(value, key)

            case list() | tuple():
                children, _ = zip(*(self._intern_rec(v) for v in value))
                items = type(value)(children)
                if not any(isinstance(r, Digest) for r in items):
                    return super().put(items, key)
                return super().put(DigestedIterable(items), key)

            case dict() if not value:
                return super().put(value, key)

            case dict():
                kk, _ = zip(*(self._intern_rec(k) for k in value))
                vv, _ = zip(*(self._intern_rec(v) for v in value.values()))
                items = dict(zip(kk, vv))
                if not any(isinstance(r, Digest) for r in (*items.keys(), *items.values())):
                    return super().put(items, key)
                return super().put(DigestedDict(items), key)

            case _:
                return super().put(value, key)

    def get(self, key: Digest | Any) -> Any:
        if not isinstance(key, Digest):
            return key  # passing through an actual value from Digested.mend
        value = super().get(key)

        match value:
            case Digested():
                return value.mend(self)
            case _:
                return value


class CallStorage(StorageBackend):
    """Abstract domain interface for call storage."""

    @abstractmethod
    def save(self, call: Call) -> Digest: ...

    @abstractmethod
    def load(self, key: Digest | str) -> Call: ...

    @abstractmethod
    def query(self, template: QueryCall) -> Iterable[Call]: ...


class CallMixin(CallStorage, StorageBackend):
    """Bridges :class:`CallStorage` with :class:`StorageBackend` primitives.

    Implements ``save`` and ``load`` using ``put`` and ``get``, deriving the
    storage key from the call's lookup key.  Also provides ``transform`` and
    ``query`` domain methods.

    Concrete classes inherit from this and a :class:`StorageBackend`
    implementation to get a fully functional call storage.
    """

    def save(self, call: Call) -> Digest:
        key = call.to_lookup_key()
        logger.debug("Saving call %s", key)
        if self.contains(str(key)):
            self.evict(str(key))
        return self.put(call, key)

    def load(self, key: Digest | str) -> Call:
        if len(key) < DIGEST_LENGTH:
            key = self.expand(key)
        else:
            key = Digest(key)
        logger.debug("Loading call with key %s", key)
        return self.get(key)

    def transform(self, func: Callable[[Call], Call] | None = None) -> None:
        """
        Applies a transformation function to all Call objects in the storage.

        Args:
            func (Callable[[Call], Call] | None): A function that takes a Call and returns a transformed Call.
                If None, the identity function is used (useful for re-calculating keys).
        """
        for k in list(self.list()):
            try:
                call = self.load(k)
            except KeyError:
                continue

            new_call = func(call) if func is not None else call
            new_key = new_call.to_lookup_key()
            if new_key != k:
                self.save(new_call)
                self.evict(k)
            else:
                self.save(new_call)

    def query(self, template: QueryCall) -> Iterable[Call]:
        """Find cached calls that 'match' the template.

        Returns all calls where the given arguments, results or metadata match exactly the stored ones.  Values may be
        given either as they are or as :class:`Digest`.

        Args:
            template (Call): specification for calls to return; use `None` as wildcard.

        Returns:
            Iterable[Call]: an iterable over all matching call objects
        """

        def none_or_equal(a, b):
            return a is None or digest(a) == digest(b)

        for key in self.list():
            call = self.load(key)
            if template.matches(call):
                yield call
