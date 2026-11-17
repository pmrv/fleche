import bisect
import contextlib
import importlib
import logging

from abc import ABC, abstractmethod
from enum import StrEnum
from typing import Iterable, Any, Callable, Literal, Sequence, overload

from ..digest import digest, Digest, DIGEST_LENGTH
from ..call import DigestedCall, QueryCall

logger = logging.getLogger("fleche.storage")

StorageKind = Literal["value", "call"]

_STORAGE: "dict[tuple[str, StorageKind], tuple[str, Callable[..., Any] | None]]" = {
    # SQLAlchemy is slow to import, so fleche.storage.sql is imported only when
    # a config asks for it; until then its slot holds no constructor.
    ("sql", "call"): ("fleche.storage.sql.Sql", None),
}
"""The registry: ``(name, kind)`` to the qualified name of the class that holds
it, and the constructor to call.  Classes are named rather than kept so that a
re-imported module can register its classes again.
"""


def _qualified_name(cls: Any) -> str:
    return f"{cls.__module__}.{cls.__qualname__}"


def register_storage(
    name: str,
    kind: StorageKind,
    *,
    factory: "Callable[..., Any] | None" = None,
) -> "Callable[[Any], Any]":
    """Register a storage backend constructor for config (de)serialisation.

    ``fleche.config.storage_from_config({"type": name, ...}, kind)`` looks
    up ``(name, kind)`` here and calls the registered constructor with the
    remaining config keys as keyword arguments — by default the decorated
    class itself (``cls(**kwargs)``); pass an explicit *factory* when
    construction needs an alternate entry point (a classmethod, or a
    positional argument the config dict doesn't carry).

    The other direction is the class's own ``to_config()``: every registered
    class writes out its config dict by hand, ``type`` key included (there is
    no inherited default — see :func:`fleche.config.storage_to_config`).
    Registering is also what makes ``storage_to_config`` accept the class at
    all: it refuses any class not registered *exactly*, because an
    unregistered subclass would otherwise serialise under its parent's
    ``type`` and silently round-trip back as the parent.

    Used as a plain class decorator for the common case::

        @register_storage("void", kind="value")
        @dataclass(frozen=True)
        class ValueVoid(ValueMixin, VoidBackend): ...

    Or called directly, after the class is fully defined, when *factory*
    must reference one of the class's own methods::

        register_storage("memory", kind="value", factory=ValueMemory.from_config)(ValueMemory)

    A class may register under several names — ``ValuePickleFile`` is
    reachable as ``pickle``/``dill``/``cloudpickle`` via its ``with_*``
    constructors — in which case its ``to_config`` is responsible for
    picking the right one back off the instance.

    *cls* is intentionally untyped (``Any``): most registrants are
    ``StorageBackend`` subclasses, but ``Sql`` implements ``CallStorage``
    directly and registers here too.

    Raises:
        ValueError: when another class already holds ``(name, kind)``,
            including a built-in backend that is imported lazily (``"sql"``).
    """
    def decorator(cls: Any) -> Any:
        owner = _qualified_name(cls)
        held, _ = _STORAGE.get((name, kind), (owner, None))
        if held != owner:
            raise ValueError(f"{name!r} {kind} storage is already registered to {held}")
        _STORAGE[(name, kind)] = (owner, factory if factory is not None else cls)
        return cls
    return decorator


def get_storage_constructor(name: str, kind: StorageKind) -> "Callable[..., Any] | None":
    """Look up the registered constructor for ``(name, kind)``, or ``None`` if unregistered."""
    if (name, kind) not in _STORAGE:
        return None
    owner, constructor = _STORAGE[(name, kind)]
    if constructor is None:
        module, _, qualname = owner.rpartition(".")
        constructor = getattr(importlib.import_module(module), qualname)
    return constructor


def is_registered_storage(cls: type) -> bool:
    """Whether *cls* itself was passed to :func:`register_storage`.

    Deliberately an exact-class check: a subclass inherits its parent's
    ``to_config`` and would serialise under the parent's ``type``, so
    ``storage_to_config`` refuses it rather than silently round-tripping it
    back as the parent.
    """
    return any(owner == _qualified_name(cls) for owner, _ in _STORAGE.values())


class SaveError(Exception):
    pass


class AmbiguousDigestError(ValueError):
    pass


class UnverifiedEntry(KeyError):
    """An entry that is present and intact, but this storage cannot verify it.

    E.g. a pickle signed with a key the storage does not hold.  It reads as a
    miss like any ``KeyError``, but unlike a damaged entry it is never marked
    for rewriting: it may be another key holder's valid value.
    """


class Intent(StrEnum):
    """Describes the kind of operation being performed on storage.

    Mixins may use this to choose between exclusive and shared locks.

    :attr:`WRITE` always takes the exclusive lock.  :attr:`READ` is a
    **no-op** for now — the locking mixins short-circuit it and acquire
    nothing.  It is reserved for a future reader-writer lock, where reads
    would take a *shared* lock instead.  Because it currently grants **no**
    mutual exclusion, ``READ`` must never guard a read-modify-write sequence.
    """
    WRITE = "write"
    READ = "read"


def _longest_common_prefix_length(s1: str, s2: str) -> int:
    for i, (c1, c2) in enumerate(zip(s1, s2)):
        if c1 != c2:
            return i
    return min(len(s1), len(s2))


def _apply_shrink(
    shrink_many: Callable[..., "tuple[Digest, ...]"], keys: "tuple[Digest | str, ...]"
) -> "Digest | tuple[Digest, ...]":
    """Shared empty-check + single/tuple unwrap for a batched ``shrink(*keys)`` overload.

    Calls ``shrink_many(*keys)``, which must return a same-length tuple of
    :class:`~fleche.digest.Digest`, and unwraps it to a single :class:`~fleche.digest.Digest` when *keys*
    has length one. Shared by :meth:`KeyManagement.shrink` and
    :meth:`~fleche.caches.BaseCache.shrink`, whose batched ``_shrink``
    implementations differ but whose public overload boilerplate does not.
    """
    if not keys:
        raise TypeError("shrink() requires at least one key")
    out = shrink_many(*keys)
    return out[0] if len(keys) == 1 else out


def _resolve_prefix(
    key: "Digest | str", candidates: "Iterable[Digest]", *, dedupe: bool = False
) -> Digest:
    """Return the unique Digest for *key* prefix, or raise KeyError / AmbiguousDigestError.

    With ``dedupe=False`` (the default), *candidates* must contain at most two
    entries (the two lexicographically smallest keys that start with *key*);
    callers are responsible for fetching them efficiently (e.g. via a
    ``LIKE … LIMIT 2`` query for SQL backends).

    With ``dedupe=True``, *candidates* is first reduced to its sorted unique
    values — for callers combining results from multiple sub-storages, where
    the same digest may legitimately appear more than once.
    """
    candidates = sorted(set(candidates)) if dedupe else list(candidates)
    if not candidates:
        raise KeyError(key)
    if len(candidates) == 1:
        return candidates[0]
    lcp = _longest_common_prefix_length(candidates[0], candidates[1])
    raise AmbiguousDigestError(
        f"Short digest {key} is ambiguous; expands to: {list(candidates)}; "
        f"need at least {lcp + 1} characters."
    )


class OperationContext(ABC):
    """Minimal base that exposes the :meth:`~fleche.storage.base.OperationContext._operation_context` hook.

    Both :class:`~fleche.storage.base.KeyManagement` (storage layer) and :class:`~fleche.caches.BaseCache`
    (cache layer) inherit from this class so that the same thread-safety mixins
    (:class:`~fleche.storage.thread_safe.SerializingMixin`,
    :class:`~fleche.storage.thread_safe.PerKeyLockMixin`) can attach to either
    layer without duplication.
    """

    @contextlib.contextmanager
    def _operation_context(self, key: Digest | str, *, intent: Intent = Intent.WRITE):
        """Context manager entered around every operation on ``key``.

        The base implementation is a no-op.  Override in a mixin to inject
        any resource scoped to the operation — a threading lock, a SQLAlchemy
        session, an open file handle, a decompression stream, etc.

        Receiving ``key`` lets implementations choose between a single global
        resource (ignore the key) or per-key resources (e.g. a striped lock
        table or a key-specific file handle).

        ``intent`` describes the kind of operation being performed.  Mixins
        may use it to choose between exclusive and shared locks.  Currently
        the only defined value is :attr:`~fleche.storage.base.Intent.WRITE` (the default).

        **Composing multiple mixins**: use ``super()`` to chain so that every
        mixin in the MRO gets to wrap the operation::

            @contextlib.contextmanager
            def _operation_context(self, key, *, intent=Intent.WRITE):
                with self._lock:                   # this mixin's resource
                    with super()._operation_context(key, intent=intent):
                        yield
        """
        yield


class KeyManagement(OperationContext):
    """Abstract base providing key-management helpers for any keyed storage.

    Subclasses must implement ``list``, ``_evict``, and ``_contains``.
    The concrete helpers ``evict``, ``contains``, ``expand``, and ``shrink``
    are implemented here once and inherited by all storage classes.

    Every public operation enters :meth:`~fleche.storage.base.OperationContext._operation_context` around the
    compound work it performs, so mixins can inject an operation-scoped
    resource (e.g. a threading lock, a SQLAlchemy session, a file handle)
    without overriding every method individually.
    """

    @abstractmethod
    def list(self) -> Iterable[Digest]: ...

    @abstractmethod
    def _evict(self, key: Digest) -> None: ...

    @abstractmethod
    def _contains(self, key: Digest) -> bool: ...

    def evict(self, key: Digest | str) -> None:
        """Removes the entry corresponding to the key from the storage."""
        with self._operation_context(key):
            self._evict(self._normalize_key(key))

    def contains(self, key: Digest | str) -> bool:
        """Return True if the key is present in the storage, False otherwise."""
        with self._operation_context(key):
            try:
                key = self._normalize_key(key)
            except KeyError:
                return False
            return self._contains(key)

    def expand(self, key: Digest | str) -> Digest:
        """Expands a short-hand digest to the full length one."""
        with self._operation_context(key):
            if len(key) >= DIGEST_LENGTH:
                return Digest(str(key))
            if len(key) < 4:
                raise KeyError(key)

            return _resolve_prefix(str(key), self._prefix_candidates(str(key)))

    def _prefix_candidates(self, prefix: str) -> "Iterable[Digest]":
        """Return at most the two lexicographically smallest keys starting with *prefix*.

        Default: a Python-side filter over :meth:`list`. Override for a
        backend that can push the prefix scan down (e.g. SQL ``LIKE ... LIMIT
        2``); :meth:`~fleche.storage.base.KeyManagement.expand` only needs the two smallest candidates to decide
        between a unique match and an :class:`~fleche.storage.base.AmbiguousDigestError`.
        """
        return sorted(k for k in self.list() if k.startswith(prefix))[:2]

    @overload
    def shrink(self, key: Digest | str, /) -> Digest: ...
    @overload
    def shrink(self, key: Digest | str, /, *keys: Digest | str) -> "tuple[Digest, ...]": ...
    def shrink(self, *keys: Digest | str) -> "Digest | tuple[Digest, ...]":
        """Find the shortest substring(s) that unambiguously reference each key.

        With a single key, returns one :class:`~fleche.digest.Digest`.  With multiple keys,
        returns a tuple of :class:`~fleche.digest.Digest` in the same order as the inputs;
        the batched form fetches ``list()`` once instead of per-key, which
        matters on backends where listing is expensive (e.g. SQL, filesystem).
        """
        return _apply_shrink(self._shrink, keys)

    def _shrink(self, *keys: Digest | str) -> "tuple[Digest, ...]":
        # Enter _operation_context for each key so subclasses with locks
        # (e.g. PerKeyLockMixin) still observe the read.  The list() snapshot
        # is taken once inside the combined context.
        with contextlib.ExitStack() as stack:
            for k in keys:
                stack.enter_context(self._operation_context(k))
            sorted_all = sorted(self.list())
            return tuple(self._shrink_one(k, sorted_all) for k in keys)

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
    operations.  Higher-level classes (:class:`~fleche.storage.base.ValueMixin`, :class:`CallMixin`)
    add domain-specific logic on top.

    Backends that are constructible from a config dict additionally spell out
    a ``to_config()`` returning that dict — see :func:`register_storage`.
    There is deliberately no default implementation here: the config keys of
    a backend are a hand-maintained contract, not whatever its dataclass
    fields happen to be.
    """

    @abstractmethod
    def put(self, value: Any, key: Digest) -> Digest:
        """Write *value* under *key*, replacing any entry already there.

        Must be atomic with respect to ``_contains`` and ``get``: until the
        entry is complete they see the previous state, never a partial one —
        also if the process dies mid-write.  :meth:`ValueMixin.save` skips
        keys ``_contains`` reports and rewrites one only after a failed
        :meth:`~ValueMixin.load`, so a key published early stays torn until
        something tries to read it.  If the value cannot be serialised, raise
        :class:`SaveError` and leave no entry under *key*.
        """

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
    """Bridges :class:`~fleche.storage.base.ValueStorage` with :class:`~fleche.storage.base.StorageBackend` primitives.

    Implements ``save`` and ``load`` using ``put`` and ``get``.
    Concrete classes inherit from this and a :class:`~fleche.storage.base.StorageBackend`
    implementation to get a fully functional value storage.

    ``save`` skips keys already present.  An entry that is present but cannot
    be read — truncated by a power loss or an older fleche, damaged on disk —
    would then never be rewritten, so a failed ``load`` of a present key marks
    it, and the next ``save`` of that key writes it again.  An
    :class:`UnverifiedEntry` is not marked: it is intact, only not verifiable
    here, e.g. signed with a key this storage does not hold.  Nothing is
    evicted on read.
    """

    @property
    def _unreadable(self) -> "set[Digest]":
        """Keys whose entry is present but failed to load in this process.

        Kept in the instance ``__dict__`` rather than as a dataclass field:
        backends are frozen dataclasses, and this is process-local state, not
        configuration, so it stays out of ``__init__``, ``__eq__`` and
        ``to_config``.  Set operations are atomic under the GIL.
        """
        return self.__dict__.setdefault("_unreadable_keys", set())

    def save(self, value: Any, key: Digest | None = None) -> Digest:
        """Store *value* under *key* (its digest by default), unless already present.

        Keys are content digests, so a readable entry already under *key*
        holds an equal value and writing it again is pure I/O.  Skipping it
        relies on every backend's ``put`` publishing a key only once its
        entry is complete; an entry that is present but failed to
        :meth:`load` is written again regardless.
        """
        if key is None:
            key = digest(value)
        with self._operation_context(key):
            if key not in self._unreadable and self._contains(key):
                logger.debug("Value with key %s already stored", key)
                return key
            logger.debug("Saving value with key %s", key)
            stored = self.put(value, key)
            self._unreadable.discard(key)
            return stored

    def load(self, key: Digest | str) -> Any:
        with self._operation_context(key):
            key = self._normalize_key(key)
            logger.debug("Loading value with key %s", key)
            try:
                return self.get(key)
            except UnverifiedEntry:
                raise
            except Exception:
                # Present but unreadable: let the next save rewrite it.  The
                # exception itself is the backend's to choose — a KeyError
                # reads as a miss, anything else (e.g. a version check the
                # user asked for) still reaches the caller.
                if self._contains(key):
                    logger.warning("Value %s is stored but unreadable; the next save rewrites it", key)
                    self._unreadable.add(key)
                raise


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
            func: A function that takes a :class:`~fleche.call.DigestedCall` and returns a transformed
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
    """Bridges :class:`~fleche.storage.base.CallStorage` with :class:`~fleche.storage.base.StorageBackend` primitives.

    Implements ``save``, ``load``, and ``query`` using ``put`` and ``get``,
    deriving the storage key from the call's lookup key.  ``transform`` is
    inherited from :class:`~fleche.storage.base.CallStorage`.

    Concrete classes inherit from this and a :class:`~fleche.storage.base.StorageBackend`
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
        given either as they are or as :class:`~fleche.digest.Digest`.

        Args:
            template (Call): specification for calls to return; use `None` as wildcard.

        Returns:
            Iterable[DigestedCall]: an iterable over all matching digested call objects
        """

        for key in self.list():
            call = self.load(key)
            if template.matches(call):
                yield call
