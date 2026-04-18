"""Thread-safety mixins for storage classes.

These mixins subclass :class:`~fleche.storage.base.KeyManagement` and override
``_operation_context`` to inject a threading lock around every storage
operation.  Because every concrete storage class (``ValueMemory``, ``Sql``, …)
ultimately inherits from ``KeyManagement``, these mixins compose with any
backend via Python's MRO::

    @dataclass(frozen=True)
    class ThreadSafeValueMemory(SerializingMixin, ValueMemory): ...

Choose the mixin based on the access pattern you need:

* :class:`SerializingMixin` — single global ``RLock``.  Every operation waits
  for the same lock, so the storage is touched by at most one thread at a
  time.  Use when the backing store is not thread-safe and per-key parallelism
  is not needed.

* :class:`PerKeyLockMixin` — a striped lock table, one ``RLock`` per key.
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

from .base import KeyManagement
from ..digest import Digest


class _PicklableLock:
    """A ``threading.Lock`` wrapper that survives pickle round-trips.

    The lock is re-initialised fresh on unpickle — its acquired/released state
    is **not** preserved.  This is intentionally an in-process pickling aid
    (e.g. for ``multiprocessing`` spawn or ``joblib``), **not** an
    inter-process synchronisation primitive: each process gets its own
    independent lock that shares no state with locks in other processes.
    """

    def __init__(self):
        self._lock = threading.Lock()

    def __reduce__(self):
        return (type(self), ())

    def __enter__(self):
        return self._lock.__enter__()

    def __exit__(self, *args):
        return self._lock.__exit__(*args)


class _PicklableRLock:
    """A ``threading.RLock`` wrapper that survives pickle round-trips.

    Same in-process-only semantics as :class:`_PicklableLock`; reentrant so
    that nested acquisitions (e.g. ``expand`` inside ``load``) do not deadlock.
    """

    def __init__(self):
        self._lock = threading.RLock()

    def __reduce__(self):
        return (type(self), ())

    def __enter__(self):
        return self._lock.__enter__()

    def __exit__(self, *args):
        return self._lock.__exit__(*args)


@dataclass(frozen=True)
class SerializingMixin(KeyManagement):
    """Mixin that serializes all storage operations behind a single reentrant lock.

    Place before the concrete storage class in the MRO::

        @dataclass(frozen=True)
        class SerializingValueMemory(SerializingMixin, ValueMemory): ...
    """

    _lock: _PicklableRLock = field(
        default_factory=_PicklableRLock, init=False, repr=False, compare=False
    )

    @contextlib.contextmanager
    def _operation_context(self, key):
        with self._lock:
            with super()._operation_context(key):
                yield


# Module-level storage for per-instance key-lock tables.  Keyed by id(instance)
# so instances need not be hashable (frozen dataclasses with list fields are not).
# Entries are evicted via weakref.finalize when the owning instance is GC'd,
# so nothing is stored on the instance itself and pickle works transparently.
_per_key_lock_tables: dict[int, tuple] = {}
_per_key_tables_lock: threading.Lock = threading.Lock()


def _evict_lock_table(inst_id: int) -> None:
    with _per_key_tables_lock:
        _per_key_lock_tables.pop(inst_id, None)


class PerKeyLockMixin(KeyManagement):
    """Mixin that locks per-key so concurrent ops on different keys proceed in parallel.

    A lightweight ``threading.Lock`` guards the lock-table itself; once the
    per-key ``RLock`` is obtained the table lock is released, so two threads
    operating on *different* keys never block each other.  Operations on the
    *same* key are serialized by the per-key lock, which is reentrant to
    allow nested calls (e.g. ``expand`` inside ``load``).

    Place before the concrete storage class in the MRO::

        @dataclass(frozen=True)
        class PerKeyValueMemory(PerKeyLockMixin, ValueMemory): ...
    """

    def _get_key_lock(self, key: Digest | str) -> threading.RLock:
        inst_id = id(self)
        try:
            key_locks, meta_lock = _per_key_lock_tables[inst_id]
        except KeyError:
            with _per_key_tables_lock:
                if inst_id not in _per_key_lock_tables:
                    _per_key_lock_tables[inst_id] = (weakref.WeakValueDictionary(), _PicklableLock())
                    weakref.finalize(self, _evict_lock_table, inst_id)
                key_locks, meta_lock = _per_key_lock_tables[inst_id]
        with meta_lock:
            # Hold a strong reference so the lock is not collected between
            # creation and return — WeakValueDictionary only stores a weak ref.
            lock = key_locks.get(key)
            if lock is None:
                lock = threading.RLock()
                key_locks[key] = lock
            return lock

    @contextlib.contextmanager
    def _operation_context(self, key):
        with self._get_key_lock(key):
            with super()._operation_context(key):
                yield

