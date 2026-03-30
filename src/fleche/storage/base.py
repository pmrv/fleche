import logging
from dataclasses import dataclass
from numbers import Number

from abc import ABC, abstractmethod
from typing import Iterable, Any, Callable, Self

from ..digest import digest, Digest, DIGEST_LENGTH
from ..call import Call, QueryCall

logger = logging.getLogger("fleche.storage")


class SaveError(Exception):
    pass


class AmbiguousDigestError(ValueError):
    pass


class StorageBase(ABC):
    """Shared functionality between value and call storages."""

    @abstractmethod
    def list(self) -> Iterable[Digest]: ...

    def evict(self, key: Digest | str) -> None:
        """Removes the entry corresponding to the key from the storage."""
        if len(key) < DIGEST_LENGTH:
            key = self.expand(key)
        else:
            key = Digest(key)
        self._evict(key)

    @abstractmethod
    def _evict(self, key: Digest) -> None: ...

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

    def contains(self, key: Digest | str) -> bool:
        if len(key) < DIGEST_LENGTH:
            try:
                key = self.expand(key)
            except KeyError:
                return False
        else:
            key = Digest(key)
        return self._contains(key)

    @abstractmethod
    def _contains(self, key: Digest) -> bool: ...


class Storage(StorageBase):
    """Abstract base class for defining storage mechanisms."""

    def save(self, value: Any, key: Digest | None = None) -> Digest:
        if key is None:
            key = digest(value)
        logger.debug("Saving value with key %s", key)
        return self._save(value, key)

    @abstractmethod
    def _save(self, value: Any, key: Digest) -> Digest: ...

    def load(self, key: Digest | str) -> Any:
        if len(key) < DIGEST_LENGTH:
            key = self.expand(key)
        else:
            key = Digest(key)
        logger.debug("Loading value with key %s", key)
        return self._load(key)

    @abstractmethod
    def _load(self, key: Digest) -> Any: ...

    def _contains(self, key: Digest) -> bool:
        try:
            self._load(key)
            return True
        except KeyError:
            return False


class Digested(ABC):
    @abstractmethod
    def underlying(self): ...

    # mess with our hash to ensure that we are referentially transparent with respect to the underlying list.
    # For the replacement of the 'real' list with the 'digested' list to be invisible to caches, they must hash to the
    # same values.
    def __digest__(self):
        return digest(self.underlying())

    @abstractmethod
    def mend(self, storage): ...


@dataclass
class DigestedIterable(Digested):
    items: list | tuple

    def underlying(self):
        return self.items

    def mend(self, storage: 'DestructuringStorage') -> list | tuple:
        return type(self.items)(map(storage._load, self.items))


@dataclass
class DigestedDict(Digested):
    items: dict

    def underlying(self):
        return self.items

    def mend(self, storage: 'DestructuringStorage') -> dict:
        return {storage._load(k): storage._load(v) for k, v in self.items.items()}


@dataclass
class DestructuringStorage(Storage):
    """Special cases certain types to enable to store their constituents separately.

    This allows us to leverage redundancy in common data to save on storage.

    Instead of saving values passed to :meth:`DestructuringStorage.save` as a single blob, break supported types into
    smaller values and save these into the underlying storage :attr:`DestructuringStorage.storage`.  Instead of the full
    object a :class:`.Digested` placeholder is created that contains digests and fragments and saved into the same
    storage.  On loading the placeholder is retrieved and the constituents are by digest to recreate the original value.

    Supported types for destructuring are `tuple`, `list`, and `dict`.

    Args:
        storage (:class:`Storage`): underlying storage
        remaining_depth (int): elements whose depth is strictly less than this are inlined (not stored separately).
            Use 0 to store every element separately, negative values to store scalars separately too."""
    storage: Storage
    remaining_depth: int = 0

    def __post_init__(self):
        if isinstance(self.storage, DestructuringStorage):
            raise ValueError("DestructuringStorage cannot wrap another DestructuringStorage")

    def _intern_rec(self, value: Any) -> tuple[Any, int | float]:
        """Post-order traversal: recurse to leaves, decide inline-vs-store on the way back up.

        Returns ``(result, depth)`` where *result* is the plain value when ``depth < remaining_depth``
        (the element is inlined in its parent's :class:`Digested` wrapper) or a :class:`Digest` when
        the element was written to storage separately.  Every node in the structure is visited exactly
        once (O(n)), unlike a separate depth-counting pass.
        """
        match value:
            case list() | tuple():
                children = [self._intern_rec(v) for v in value]
                depth = 1 + max((d for _, d in children), default=0)

                if depth < self.remaining_depth:
                    # Inline this container — reuse the original object if nothing was transformed (req 4)
                    if all(r is v for (r, _), v in zip(children, value)):
                        return value, depth
                    return type(value)(r for r, _ in children), depth

                # Store this container separately
                items = type(value)(r for r, _ in children)
                # If every child is a plain value (no Digest), store a plain container (req 3)
                if not any(isinstance(r, Digest) for r in items):
                    return self.storage.save(items), depth
                return self.storage.save(DigestedIterable(items)), depth

            case dict():
                kk = [self._intern_rec(k) for k in value]
                vv = [self._intern_rec(v) for v in value.values()]
                depth = 1 + max(
                    max((d for _, d in kk), default=0),
                    max((d for _, d in vv), default=0),
                )

                if depth < self.remaining_depth:
                    # Inline this dict — reuse original if nothing changed (req 4)
                    if all(rk is k and rv is v
                           for (rk, _), k, (rv, _), v
                           in zip(kk, value.keys(), vv, value.values())):
                        return value, depth
                    return {rk: rv for (rk, _), (rv, _) in zip(kk, vv)}, depth

                # Store this dict separately
                items = {rk: rv for (rk, _), (rv, _) in zip(kk, vv)}
                # If no key or value is a Digest, store a plain dict (req 3)
                if not any(isinstance(r, Digest) for r in (*items.keys(), *items.values())):
                    return self.storage.save(items), depth
                return self.storage.save(DigestedDict(items)), depth

            case Number() | str() | bytes():
                depth = 0
                if depth < self.remaining_depth:
                    return value, depth
                return self.storage.save(value), depth

            case _:
                return self.storage.save(value), float('inf')

    def _save(self, value: Any, key: Digest) -> Digest:
        if isinstance(value, Digest):
            return value

        match value:
            case list() | tuple():
                children = [self._intern_rec(v) for v in value]
                items = type(value)(r for r, _ in children)
                if not any(isinstance(r, Digest) for r in items):
                    # All children inlined: store plain container (req 3)
                    # Reuse original object if nothing changed (req 4)
                    if all(r is v for (r, _), v in zip(children, value)):
                        return self.storage.save(value, key)
                    return self.storage.save(items, key)
                return self.storage.save(DigestedIterable(items), key)

            case dict():
                kk = [self._intern_rec(k) for k in value]
                vv = [self._intern_rec(v) for v in value.values()]
                items = {rk: rv for (rk, _), (rv, _) in zip(kk, vv)}
                if not any(isinstance(r, Digest) for r in (*items.keys(), *items.values())):
                    # All children inlined: store plain dict (req 3)
                    return self.storage.save(items, key)
                return self.storage.save(DigestedDict(items), key)

            case _:
                return self.storage.save(value, key)

    def _load(self, key: Digest | Any) -> Any:
        if not isinstance(key, Digest):
            return key  # passing through an actual value from Digested.mend
        value = self.storage.load(key)

        match value:
            case Digested():
                return value.mend(self)
            case _:
                return value

    def _contains(self, key: Digest) -> bool:
        return self.storage.contains(key)

    def _evict(self, key: Digest) -> None:
        self.storage.evict(key)

    def list(self) -> Iterable[Digest]:
        return self.storage.list()


class CallStorage(StorageBase):
    """Special storage for saving :class:`Call` instances."""

    def save(self, call: Call) -> Digest:
        key = call.to_lookup_key()
        logger.debug("Saving call %s", key)
        if self.contains(str(key)):
            self.evict(str(key))
        return self._save(call)

    @abstractmethod
    def _save(self, call: Call) -> Digest: ...

    def load(self, key: str) -> Call:
        if len(key) < DIGEST_LENGTH:
            key = self.expand(key)
        else:
            key = Digest(key)
        logger.debug("Loading call with key %s", key)
        return self._load(key)

    @abstractmethod
    def _load(self, key: Digest) -> Call: ...

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

    def _contains(self, key: Digest) -> bool:
        try:
            self._load(key)
            return True
        except KeyError:
            return False


@dataclass(frozen=True, slots=True)
class CallStorageAdapter(CallStorage):
    """Implement a CallStorage from a generic Storage."""

    storage: Storage

    def _save(self, call: Call) -> Digest:
        return self.storage.save(call, call.to_lookup_key())

    def _load(self, key: Digest) -> Call:
        return self.storage.load(key)

    def _contains(self, key: Digest) -> bool:
        return self.storage.contains(key)

    def _evict(self, key: Digest) -> None:
        self.storage.evict(key)

    def list(self) -> Iterable[Digest]:
        return self.storage.list()
