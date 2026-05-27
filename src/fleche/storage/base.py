import bisect
import contextlib
import logging

from abc import ABC, abstractmethod
from typing import Iterable, Any, Callable, Sequence, overload

from ..digest import digest, Digest, DIGEST_LENGTH
from ..call import DigestedCall, QueryCall

logger = logging.getLogger("fleche.storage")


class SaveError(Exception):
    pass


class AmbiguousDigestError(ValueError):
    pass


def _longest_common_prefix_length(s1: str, s2: str) -> int:
    for i, (c1, c2) in enumerate(zip(s1, s2)):
        if c1 != c2:
            return i
    return min(len(s1), len(s2))


def _resolve_prefix(key: str, candidates: list[Digest]) -> Digest:
    """Return the unique Digest for *key* prefix, or raise KeyError / AmbiguousDigestError.

    *candidates* must contain at most two entries (the two lexicographically
    smallest keys that start with *key*); callers are responsible for fetching
    them efficiently (e.g. via a ``LIKE … LIMIT 2`` query for SQL backends).
    """
    if not candidates:
        raise KeyError(key)
    if len(candidates) == 1:
        return candidates[0]
    lcp = _longest_common_prefix_length(candidates[0], candidates[1])
    raise AmbiguousDigestError(
        f"Short digest {key} is ambiguous; need at least {lcp+1} characters."
    )


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

            candidates = sorted(k for k in self.list() if k.startswith(key))
            return _resolve_prefix(str(key), candidates[:2])

    @overload
    def shrink(self, key: Digest | str, /) -> Digest: ...
    @overload
    def shrink(self, key: Digest | str, /, *keys: Digest | str) -> "tuple[Digest, ...]": ...
    def shrink(self, *keys: Digest | str) -> "Digest | tuple[Digest, ...]":
        """Find the shortest substring(s) that unambiguously reference each key.

        With a single key, returns one :class:`Digest`.  With multiple keys,
        returns a tuple of :class:`Digest` in the same order as the inputs;
        the batched form fetches ``list()`` once instead of per-key, which
        matters on backends where listing is expensive (e.g. SQL, filesystem).
        """
        if not keys:
            raise TypeError("shrink() requires at least one key")
        # Enter _operation_context for each key so subclasses with locks
        # (e.g. PerKeyLockMixin) still observe the read.  The list() snapshot
        # is taken once inside the combined context.
        with contextlib.ExitStack() as stack:
            for k in keys:
                stack.enter_context(self._operation_context(k))
            sorted_all = sorted(self.list())
            out = tuple(self._shrink_one(k, sorted_all) for k in keys)
        return out[0] if len(keys) == 1 else out

    def _shrink_one(self, key: "Digest | str", sorted_all: Sequence[str]) -> Digest:
        # Correctness: in a sorted key list, the longest prefix any *other*
        # stored key shares with `key` is the LCP with one of `key`'s two
        # immediate sorted neighbours.  Lexicographic adjacency implies
        # prefix adjacency, so any third key with a longer shared prefix
        # would have to sit strictly between `key` and the neighbour in the
        # sort order — contradicting "immediate neighbour".  Therefore
        # `max(lcp_left, lcp_right) + 1` is the shortest unambiguous length.
        s_key = str(key)
        i = bisect.bisect_left(sorted_all, s_key)
        if i == len(sorted_all) or sorted_all[i] != s_key:
            raise KeyError(key)
        lcp_left = (
            _longest_common_prefix_length(s_key, sorted_all[i - 1]) if i > 0 else 0
        )
        lcp_right = (
            _longest_common_prefix_length(s_key, sorted_all[i + 1])
            if i + 1 < len(sorted_all)
            else 0
        )
        n = max(4, max(lcp_left, lcp_right) + 1)
        if n >= len(s_key):
            raise AmbiguousDigestError(
                f"Digest {key} cannot be shrunk without becoming ambiguous!"
            )
        return Digest(s_key[:n])

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
    def save(self, call: DigestedCall) -> Digest: ...

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


class CallMixin(CallStorage, StorageBackend):
    """Bridges :class:`CallStorage` with :class:`StorageBackend` primitives.

    Implements ``save``, ``load``, and ``query`` using ``put`` and ``get``,
    deriving the storage key from the call's lookup key.  ``transform`` is
    inherited from :class:`CallStorage`.

    Concrete classes inherit from this and a :class:`StorageBackend`
    implementation to get a fully functional call storage.
    """

    def save(self, call: DigestedCall) -> Digest:
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
            return self.get(key)

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
