from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Iterable, Any, Callable

from ..digest import digest, Digest, DIGEST_LENGTH
from ..call import Call


class SaveError(Exception):
    pass


class AmbiguousDigestError(ValueError):
    pass


class Storage(ABC):
    """Abstract base class for defining storage mechanisms."""

    def save(self, value: Any, key: Digest | None = None) -> str:
        if key is None:
            key = digest(value)
        return self._save(value, key)

    @abstractmethod
    def _save(self, value: Any, key: Digest) -> str: ...

    def load(self, key: str) -> Any:
        if len(key) < DIGEST_LENGTH:
            key = self.expand(key)
        return self._load(key)

    @abstractmethod
    def _load(self, key: str) -> Any: ...

    @abstractmethod
    def list(self) -> Iterable[str]: ...

    def evict(self, key: str) -> None:
        """Removes the entry corresponding to the key from the storage."""
        if len(key) < DIGEST_LENGTH:
            key = self.expand(key)
        self._evict(key)

    @abstractmethod
    def _evict(self, key: str) -> None: ...

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


class CallStorage(Storage):
    """Special storage for saving :class:`Call` instances."""

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
                self.save(new_call, key=new_key)
                self.evict(k)
            else:
                self.save(new_call, key=k)

    def redigest(self) -> None:
        """
        Re-calculates lookup keys for all Call objects in the storage.
        """
        self.transform(None)
