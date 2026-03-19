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

    @classmethod
    @abstractmethod
    def sunder(cls, save: Callable[[Any], Digest], value): ...


@dataclass
class DigestedIterable(Digested):
    items: list | tuple

    def underlying(self):
        return self.items

    @classmethod
    def sunder(cls, save: Callable[[Any], Digest], value: list | tuple) -> Self:
        return cls(type(value)(save(v) for v in value))

    def mend(self, storage: 'DestructuringStorage') -> list | tuple:
        return type(self.items)(map(storage._load, self.items))


@dataclass
class DigestedDict(Digested):
    items: dict

    def underlying(self):
        return self.items

    @classmethod
    def sunder(cls, save: Callable[[Any], Digest], value: dict) -> Self:
        return cls({save(k): save(v) for k, v in value.items()})

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
        remaining_depth (int): destructure supported type until this 'nesting level' remains"""
    storage: Storage
    remaining_depth: int = 0

    def _depth(self, value: Any):
        match value:
            case list() | tuple():
                return 1 + max((self._depth(v) for v in value), default=0)
            case dict():
                return 1 + max(
                        max((self._depth(k) for k in value.keys()), default=0),
                        max((self._depth(v) for v in value.values()), default=0),
                )
            case Number() | str() | bytes() | bool():
                return 1
            case _:
                return 2 ** 64

    def __post_init__(self):
        if isinstance(self.storage, DestructuringStorage):
            raise ValueError("DestructuringStorage cannot wrap another DestructuringStorage")

    def _save(self, value: Any, key: Digest) -> Digest:
        def depth_aware_save(value):
            """recursively save content values iff they have more nested levels than given cutoff to avoid putting
            each and every int/float/etc into its own storage bin."""
            if self._depth(value) <= self.remaining_depth:
                return value
            else:
                return self.save(value)

        if isinstance(value, Digest):
            return value
        match value:
            case list() | tuple():
                return self.storage.save(DigestedIterable.sunder(depth_aware_save, value))
            case dict():
                return self.storage.save(DigestedDict.sunder(depth_aware_save, value))
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
