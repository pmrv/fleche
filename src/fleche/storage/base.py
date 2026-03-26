import logging
from dataclasses import dataclass

from abc import ABC, abstractmethod
from typing import Iterable, Any, Callable

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


@dataclass
class DigestedIterable(Digested):
    items: Iterable

    def underlying(self):
        return self.items


@dataclass
class DigestedDict(Digested):
    items: dict

    def underlying(self):
        return self.items


class DestructuringMixin:
    """Mixin that recursively destructures collections on save/load.

    Place before a concrete :class:`Storage` in the MRO to add destructuring
    behavior.  Lists, tuples, and dicts are broken apart so each element is
    stored independently; on load the original structure is reassembled.

    Example::

        class DestructuringMemory(DestructuringMixin, Memory):
            pass

        dm = DestructuringMemory(storage={})
        key = dm.save([1, [2, 3]])
        assert dm.load(key) == [1, [2, 3]]
    """

    def _save(self, value: Any, key: Digest) -> Digest:
        if isinstance(value, Digest):
            return value
        match value:
            case list() | tuple():
                wrapped = DigestedIterable(type(value)(self.save(v) for v in value))
                return super()._save(wrapped, digest(wrapped))
            case dict():
                wrapped = DigestedDict({self.save(k): self.save(v) for k, v in value.items()})
                return super()._save(wrapped, digest(wrapped))
            case _:
                return super()._save(value, key)

    def _load(self, key: Digest) -> Any:
        value = super()._load(key)

        match value:
            case DigestedIterable(items=items):
                return type(items)(self.load(v) for v in items)
            case DigestedDict(items=items):
                return {self.load(k): self.load(v) for k, v in items.items()}
            case _:
                return value


@dataclass
class _DelegatingStorage(Storage):
    """Storage that delegates all operations to a wrapped storage instance."""

    storage: Storage

    def _save(self, value: Any, key: Digest) -> Digest:
        return self.storage.save(value, key)

    def _load(self, key: Digest) -> Any:
        return self.storage.load(key)

    def _contains(self, key: Digest) -> bool:
        return self.storage.contains(key)

    def _evict(self, key: Digest) -> None:
        return self.storage.evict(key)

    def list(self) -> Iterable[Digest]:
        return self.storage.list()


@dataclass
class DestructuringStorage(DestructuringMixin, _DelegatingStorage):
    """Storage wrapper that recursively destructures collections.

    This is a convenience class combining :class:`DestructuringMixin` with
    delegation to a wrapped storage.  Prefer using :class:`DestructuringMixin`
    directly as a mixin with a concrete storage class when possible.
    """

    def __post_init__(self):
        if isinstance(self.storage, DestructuringMixin):
            raise ValueError("DestructuringStorage cannot wrap a storage that already uses DestructuringMixin")


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
