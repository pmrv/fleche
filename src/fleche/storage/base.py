from __future__ import annotations
from dataclasses import dataclass

from abc import ABC, abstractmethod
from typing import Iterable, Any, Callable

from ..digest import digest, Digest, DIGEST_LENGTH
from ..call import Call


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


class Storage(StorageBase):
    """Abstract base class for defining storage mechanisms."""

    def save(self, value: Any, key: Digest | None = None) -> Digest:
        if key is None:
            key = digest(value)
        return self._save(value, key)

    @abstractmethod
    def _save(self, value: Any, key: Digest) -> Digest: ...

    def load(self, key: Digest | str) -> Any:
        if len(key) < DIGEST_LENGTH:
            key = self.expand(key)
        else:
            key = Digest(key)
        return self._load(key)

    @abstractmethod
    def _load(self, key: Digest) -> Any: ...


class CallStorage(StorageBase):
    """Special storage for saving :class:`Call` instances."""

    def save(self, call: Call) -> Digest:
        return self._save(call)

    @abstractmethod
    def _save(self, call: Call) -> Digest: ...

    def load(self, key: str) -> Call:
        if len(key) < DIGEST_LENGTH:
            key = self.expand(key)
        else:
            key = Digest(key)
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

    def query(self, template: Call) -> Iterable[Call]:
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
        def fits(call: Call) -> bool:
            return (
                    none_or_equal(template.name, call.name)
                and none_or_equal(template.module, call.module)
                and none_or_equal(template.version, call.version)
                and none_or_equal(template.result, call.result)
                and (template.arguments is None \
                        or all(none_or_equal(v, call.arguments[k]) for k, v in template.arguments.items()))
            )
        for key in self.list():
            call = self.load(key)
            if fits(call):
                yield call


@dataclass(frozen=True, slots=True)
class CallStorageAdapter(CallStorage):
    """Implement a CallStorage from a generic Storage."""
    storage: Storage

    def _save(self, call: Call) -> Digest:
        return self.storage.save(call, call.to_lookup_key())

    def _load(self, key: Digest) -> Call:
        return self.storage.load(key)

    def _evict(self, key: Digest) -> None:
        self.storage.evict(key)

    def list(self) -> Iterable[Digest]:
        return self.storage.list()
