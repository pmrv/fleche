import logging

from abc import ABC, abstractmethod
from typing import Iterable, Any, Callable

from ..digest import digest, Digest, DIGEST_LENGTH
from ..call import Call, QueryCall

logger = logging.getLogger("fleche.storage")


class SaveError(Exception):
    pass


class AmbiguousDigestError(ValueError):
    pass


class KeyManagement(ABC):
    """Abstract base providing key-management helpers for any keyed storage.

    Subclasses must implement ``list``, ``_evict``, and ``_contains``.
    The concrete helpers ``evict``, ``contains``, ``expand``, and ``shrink``
    are implemented here once and inherited by all storage classes.
    """

    @abstractmethod
    def list(self) -> Iterable[Digest]: ...

    @abstractmethod
    def _evict(self, key: Digest) -> None: ...

    @abstractmethod
    def _contains(self, key: Digest) -> bool: ...

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
        """Find the shortest substring that is still an unambiguous reference to the same value."""
        for ln in range(4, len(key)):
            try:
                self.expand(key[:ln])
                return Digest(key[:ln])
            except AmbiguousDigestError:
                continue
        raise AmbiguousDigestError(
            f"Digest {key} cannot be shrunk without becoming ambiguous!"
        )


class StorageBackend(KeyManagement):
    """Primitive backend interface for key-value storage.

    Backends implement the low-level ``put``/``get``/``_evict``/``list``
    operations.  Higher-level classes (:class:`ValueMixin`, :class:`CallMixin`)
    add domain-specific logic on top.
    """

    @abstractmethod
    def put(self, value: Any, key: Digest) -> Digest: ...

    @abstractmethod
    def get(self, key: Digest) -> Any: ...

    def _contains(self, key: Digest) -> bool:
        try:
            self.get(key)
            return True
        except KeyError:
            return False


class ValueStorage(KeyManagement):
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


class CallStorage(KeyManagement):
    """Abstract domain interface for call storage."""

    @abstractmethod
    def save(self, call: Call) -> Digest: ...

    @abstractmethod
    def load(self, key: Digest | str) -> Call: ...

    @abstractmethod
    def query(self, template: QueryCall) -> Iterable[Call]: ...

    def transform(self, func: Callable[[Call], Call] | None = None) -> None:
        """Applies a transformation function to all Call objects in the storage.

        Args:
            func (Callable[[Call], Call] | None): A function that takes a Call
                and returns a transformed Call.  If None, the identity function
                is used (useful for re-calculating keys).
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


class CallMixin(CallStorage, StorageBackend):
    """Bridges :class:`CallStorage` with :class:`StorageBackend` primitives.

    Implements ``save``, ``load``, and ``query`` using ``put`` and ``get``,
    deriving the storage key from the call's lookup key.  ``transform`` is
    inherited from :class:`CallStorage`.

    Concrete classes inherit from this and a :class:`StorageBackend`
    implementation to get a fully functional call storage.
    """

    def save(self, call: Call) -> Digest:
        key = call.to_lookup_key()
        logger.debug("Saving call %s", key)
        if self.contains(key):
            self.evict(key)
        return self.put(call, key)

    def load(self, key: Digest | str) -> Call:
        if len(key) < DIGEST_LENGTH:
            key = self.expand(key)
        else:
            key = Digest(key)
        logger.debug("Loading call with key %s", key)
        return self.get(key)

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
