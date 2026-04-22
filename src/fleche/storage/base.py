import contextlib
import logging

from abc import ABC, abstractmethod
from typing import Iterable, Any, Callable

from ..digest import digest, Digest, DIGEST_LENGTH
from ..call import Call, DigestedCall, QueryCall

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

    Every public operation enters :meth:`_operation_context` around the
    compound work it performs, so mixins can inject an operation-scoped
    resource (e.g. a threading lock, a SQLAlchemy session, a file handle)
    without overriding every method individually.
    """

    @contextlib.contextmanager
    def _operation_context(self, key: Digest | str):
        """Context manager entered around every operation on ``key``.

        The base implementation is a no-op.  Override in a mixin to inject
        any resource scoped to the operation — a threading lock, a SQLAlchemy
        session, an open file handle, a decompression stream, etc.

        Receiving ``key`` lets implementations choose between a single global
        resource (ignore the key) or per-key resources (e.g. a striped lock
        table or a key-specific file handle).

        **Composing multiple mixins**: use ``super()`` to chain so that every
        mixin in the MRO gets to wrap the operation::

            @contextlib.contextmanager
            def _operation_context(self, key):
                with self._lock:                   # this mixin's resource
                    with super()._operation_context(key):
                        yield
        """
        yield

    @abstractmethod
    def list(self) -> Iterable[Digest]: ...

    @abstractmethod
    def _evict(self, key: Digest) -> None: ...

    @abstractmethod
    def _contains(self, key: Digest) -> bool: ...

    def evict(self, key: Digest | str) -> None:
        """Removes the entry corresponding to the key from the storage."""
        with self._operation_context(key):
            if len(key) < DIGEST_LENGTH:
                key = self.expand(key)
            else:
                key = Digest(key)
            self._evict(key)

    def contains(self, key: Digest | str) -> bool:
        with self._operation_context(key):
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
        with self._operation_context(key):
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
        with self._operation_context(key):
            for ln in range(4, len(key)):
                try:
                    self.expand(key[:ln])
                    return Digest(key[:ln])
                except AmbiguousDigestError:
                    continue
            raise AmbiguousDigestError(
                f"Digest {key} cannot be shrunk without becoming ambiguous!"
            )

    def _normalize_key(self, key: Digest | str) -> Digest:
        """Expand a short digest prefix to a full key, or wrap a full key as Digest."""
        if len(key) < DIGEST_LENGTH:
            return self.expand(key)
        return Digest(key)


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
        with self._operation_context(key):
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
        with self._operation_context(key):
            logger.debug("Saving value with key %s", key)
            return self.put(value, key)

    def load(self, key: Digest | str) -> Any:
        with self._operation_context(key):
            key = self._normalize_key(key)
            logger.debug("Loading value with key %s", key)
            return self.get(key)


class CallStorage(KeyManagement):
    """Abstract domain interface for call storage."""

    @abstractmethod
    def save(self, call: Call | DigestedCall) -> Digest: ...

    @abstractmethod
    def load(self, key: Digest | str) -> DigestedCall: ...

    @abstractmethod
    def query(self, template: QueryCall) -> Iterable[DigestedCall]: ...

    def transform(self, func: Callable[[DigestedCall], DigestedCall] | None = None) -> None:
        """Applies a transformation function to all DigestedCall objects in the storage.

        Args:
            func: A function that takes a :class:`DigestedCall` and returns a transformed
                one.  If ``None``, the identity is used (useful for re-calculating keys).
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


def _to_digested_call(raw: Call | DigestedCall) -> DigestedCall:
    """Wrap a raw stored call (whose argument/result fields are Digest values) as a DigestedCall."""
    if isinstance(raw, DigestedCall):
        return raw
    return DigestedCall(
        name=raw.name,
        arguments=raw.arguments,
        result=raw.result,
        metadata=raw.metadata,
        module=raw.module,
        version=raw.version,
        code_digest=raw.code_digest,
    )


class CallMixin(CallStorage, StorageBackend):
    """Bridges :class:`CallStorage` with :class:`StorageBackend` primitives.

    Implements ``save``, ``load``, and ``query`` using ``put`` and ``get``,
    deriving the storage key from the call's lookup key.  ``transform`` is
    inherited from :class:`CallStorage`.

    Concrete classes inherit from this and a :class:`StorageBackend`
    implementation to get a fully functional call storage.
    """

    def save(self, call: Call | DigestedCall) -> Digest:
        key = call.to_lookup_key()
        with self._operation_context(key):
            logger.debug("Saving call %s", key)
            if self.contains(key):
                self.evict(key)
            return self.put(call, key)

    def load(self, key: Digest | str) -> DigestedCall:
        with self._operation_context(key):
            key = self._normalize_key(key)
            logger.debug("Loading call with key %s", key)
            return _to_digested_call(self.get(key))

    def query(self, template: QueryCall) -> Iterable[DigestedCall]:
        """Find cached calls that 'match' the template.

        Returns all calls where the given arguments, results or metadata match exactly the stored ones.  Values may be
        given either as they are or as :class:`Digest`.

        Args:
            template (Call): specification for calls to return; use `None` as wildcard.

        Returns:
            Iterable[DigestedCall]: an iterable over all matching digested call objects
        """

        for key in self.list():
            call = self.load(key)
            if template.matches(call):
                yield call
