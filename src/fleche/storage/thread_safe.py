"""Thread-safety mixins for storage classes.

These mixins subclass :class:`~fleche.storage.base.OperationContext` and override
``_operation_context`` to inject a threading lock around every storage
operation.  Because every concrete storage class (``ValueMemory``, ``Sql``, …)
ultimately inherits from ``OperationContext`` (via ``KeyManagement``), these
mixins compose with any backend via Python's MRO::

    @dataclass(frozen=True)
    class ThreadSafeValueMemory(SerializingMixin, ValueMemory): ...

Choose the mixin based on the access pattern you need:

* :class:`SerializingMixin` — single global ``RLock``.  Every operation waits
  for the same lock, so the storage is touched by at most one thread at a
  time.  Use when the backing store is not thread-safe and per-key parallelism
  is not needed.

* :class:`~fleche.storage.thread_safe.PerKeyLockMixin` — a striped lock table, one ``RLock`` per key.
  Operations on *different* keys proceed in parallel; operations on the
  *same* key are serialized.  Use when contention is dominated by hot keys
  and the backing store supports concurrent access on disjoint keys.

Both mixins use reentrant locks so nested acquisitions (e.g. ``expand`` being
called inside ``load``) do not deadlock.
"""

import contextlib
import threading
import weakref
from dataclasses import dataclass, field

from .base import Intent, OperationContext
from ..digest import Digest


class _PicklableLock:
    """A ``threading.Lock`` wrapper that survives pickle round-trips.

    The lock is re-initialised fresh on unpickle — its acquired/released state
    is **not** preserved.  This is intentionally an in-process pickling aid
    (e.g. for ``multiprocessing`` spawn or ``joblib``), **not** an
    inter-process synchronisation primitive: each process gets its own
    independent lock that shares no state with locks in other processes.
    """

    _factory = threading.Lock

    def __init__(self):
        self._lock = self._factory()

    def __reduce__(self):
        return (type(self), ())

    def __enter__(self):
        return self._lock.__enter__()

    def __exit__(self, *args):
        return self._lock.__exit__(*args)


class _PicklableRLock(_PicklableLock):
    """A ``threading.RLock`` wrapper that survives pickle round-trips.

    Same in-process-only semantics as :class:`_PicklableLock`; reentrant so
    that nested acquisitions (e.g. ``expand`` inside ``load``) do not deadlock.
    """

    _factory = threading.RLock


@dataclass(frozen=True)
class SerializingMixin(OperationContext):
    """Mixin that serializes all storage operations behind a single reentrant lock.

    Place before the concrete storage class in the MRO::

        @dataclass(frozen=True)
        class SerializingValueMemory(SerializingMixin, ValueMemory): ...
    """

    _lock: _PicklableRLock = field(
        default_factory=_PicklableRLock, init=False, repr=False, compare=False
    )

    @contextlib.contextmanager
    def _operation_context(self, key, *, intent: Intent = Intent.WRITE):
        if intent is Intent.READ:
            # No-op for now; reserved for a future shared (reader) lock.
            yield
            return
        with self._lock:
            with super()._operation_context(key, intent=intent):
                yield


# Module-level storage for per-instance key-lock tables.  WeakKeyDictionary so
# entries are evicted automatically when the owning instance is GC'd.  Instances
# must be hashable; concrete file-backed storage classes are frozen dataclasses
# with only hashable fields (secret_key is stored as tuple[bytes, ...]).
# Nothing is stored on the instance itself, so pickle works transparently.
_per_instance_locks: weakref.WeakKeyDictionary[
    "PerKeyLockMixin",
    tuple[weakref.WeakValueDictionary[Digest | str, threading.RLock], _PicklableLock],
] = weakref.WeakKeyDictionary()
_instances_lock: threading.Lock = threading.Lock()


class PerKeyLockMixin(OperationContext):
    """Mixin that locks per-key so concurrent ops on different keys proceed in parallel.

    A lightweight ``threading.Lock`` guards the lock-table itself; once the
    per-key ``RLock`` is obtained the table lock is released, so two threads
    operating on *different* keys never block each other.  Operations on the
    *same* key are serialized by the per-key lock, which is reentrant to
    allow nested calls (e.g. ``expand`` inside ``load``).

    Instances must be hashable.  Place before the concrete storage class in the
    MRO::

        @dataclass(frozen=True)
        class PerKeyValuePickle(PerKeyLockMixin, ValuePickleFile): ...
    """

    def _get_key_lock(self, key: Digest | str) -> threading.RLock:
        try:
            key_locks, meta_lock = _per_instance_locks[self]
        except KeyError:
            with _instances_lock:
                if self not in _per_instance_locks:
                    _per_instance_locks[self] = (weakref.WeakValueDictionary(), _PicklableLock())
                key_locks, meta_lock = _per_instance_locks[self]
        with meta_lock:
            # Hold a strong reference so the lock is not collected between
            # creation and return — WeakValueDictionary only stores a weak ref.
            lock = key_locks.get(key)
            if lock is None:
                lock = threading.RLock()
                key_locks[key] = lock
            return lock

    @contextlib.contextmanager
    def _operation_context(self, key, *, intent: Intent = Intent.WRITE):
        if intent is Intent.READ:
            # No-op for now; reserved for a future shared (reader) lock.
            yield
            return
        with self._get_key_lock(key):
            with super()._operation_context(key, intent=intent):
                yield

