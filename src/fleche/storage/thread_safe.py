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

``PerKeyLockMixin`` additionally guards ``expand()`` against concurrent
``put()`` / ``_evict()`` calls via a :class:`_MutationScanLock`.  This
prevents a concurrent insert from creating a spurious
:exc:`~fleche.storage.base.AmbiguousDigestError` inside the full-key-set scan
that ``expand()`` performs.  The lock is an inverted readers-writer lock:
mutations are the *concurrent* side (multiple puts may proceed in parallel)
while a scan is the *exclusive* side (blocks new mutations and waits for
in-flight ones to drain).  ``get`` / ``load`` / ``contains`` never touch this
lock, so read throughput is unaffected.
"""

import contextlib
import threading
import weakref
from dataclasses import dataclass, field
from typing import Any

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


class _MutationScanLock:
    """Inverted readers-writer lock used by :class:`PerKeyLockMixin`.

    *Mutations* (``put`` / ``_evict``) are the concurrent side: many threads
    may hold :meth:`mutation` simultaneously, just like readers in a standard
    RWLock.  A *scan* (``expand``) is the exclusive side: it waits for all
    in-flight mutations to complete, then blocks new mutations until it
    finishes, just like a writer.

    This prevents a concurrent ``put()`` from inserting a matching-prefix key
    between ``list()`` and ``_resolve_prefix()`` inside ``expand()``, which
    would otherwise cause a spurious
    :exc:`~fleche.storage.base.AmbiguousDigestError`.

    ``get`` / ``load`` / ``contains`` never touch this lock, so read
    throughput is unaffected.  The lock is stored in the module-level
    :data:`_per_instance_locks` dict (not on the frozen-dataclass instance
    itself) so it is re-created transparently after pickle round-trips.
    """

    def __init__(self) -> None:
        self._cond = threading.Condition(threading.Lock())
        self._mutations: int = 0
        self._scanning: bool = False

    @contextlib.contextmanager
    def mutation(self):
        """Concurrent with other mutations; exclusive with an active scan."""
        with self._cond:
            while self._scanning:
                self._cond.wait()
            self._mutations += 1
        try:
            yield
        finally:
            with self._cond:
                self._mutations -= 1
                if self._mutations == 0:
                    self._cond.notify_all()

    @contextlib.contextmanager
    def scan(self):
        """Exclusive: waits for all in-flight mutations, then blocks new ones."""
        with self._cond:
            while self._scanning or self._mutations > 0:
                self._cond.wait()
            self._scanning = True
        try:
            yield
        finally:
            with self._cond:
                self._scanning = False
                self._cond.notify_all()


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


# Module-level storage for per-instance lock state.  WeakKeyDictionary so
# entries are evicted automatically when the owning instance is GC'd.  Instances
# must be hashable; concrete file-backed storage classes are frozen dataclasses
# with only hashable fields (secret_key is stored as tuple[bytes, ...]).
# Nothing is stored on the instance itself, so pickle works transparently.
#
# Each value is a 3-tuple:
#   [0] WeakValueDictionary mapping key → per-key RLock
#   [1] _PicklableLock guarding the per-key lock table
#   [2] _MutationScanLock serialising expand() against put() / _evict()
_per_instance_locks: weakref.WeakKeyDictionary[
    "PerKeyLockMixin",
    tuple[
        weakref.WeakValueDictionary[Digest | str, threading.RLock],
        _PicklableLock,
        _MutationScanLock,
    ],
] = weakref.WeakKeyDictionary()
_instances_lock: threading.Lock = threading.Lock()


class PerKeyLockMixin(KeyManagement):
    """Mixin that locks per-key so concurrent ops on different keys proceed in parallel.

    A lightweight ``threading.Lock`` guards the lock-table itself; once the
    per-key ``RLock`` is obtained the table lock is released, so two threads
    operating on *different* keys never block each other.  Operations on the
    *same* key are serialized by the per-key lock, which is reentrant to
    allow nested calls (e.g. ``expand`` inside ``load``).

    ``expand()`` additionally acquires a :class:`_MutationScanLock` in
    *scan* mode so that no concurrent ``put()`` or ``_evict()`` can insert or
    remove a key during the full-key-set scan, preventing spurious
    :exc:`~fleche.storage.base.AmbiguousDigestError`.  Concurrent mutations
    proceed in parallel when no scan is active; they block only for the
    duration of an ``expand()`` call.

    Instances must be hashable.  Place before the concrete storage class in the
    MRO::

        @dataclass(frozen=True)
        class PerKeyValuePickle(PerKeyLockMixin, ValuePickleFile): ...
    """

    def _get_instance_locks(
        self,
    ) -> tuple[
        weakref.WeakValueDictionary[Digest | str, threading.RLock],
        _PicklableLock,
        _MutationScanLock,
    ]:
        """Return the lock-state tuple for this instance, initialising it if needed."""
        try:
            return _per_instance_locks[self]
        except KeyError:
            with _instances_lock:
                if self not in _per_instance_locks:
                    _per_instance_locks[self] = (
                        weakref.WeakValueDictionary(),
                        _PicklableLock(),
                        _MutationScanLock(),
                    )
                return _per_instance_locks[self]

    def _get_key_lock(self, key: Digest | str) -> threading.RLock:
        key_locks, meta_lock, _ = self._get_instance_locks()
        with meta_lock:
            # Hold a strong reference so the lock is not collected between
            # creation and return — WeakValueDictionary only stores a weak ref.
            lock = key_locks.get(key)
            if lock is None:
                lock = threading.RLock()
                key_locks[key] = lock
            return lock

    def _get_mutation_scan_lock(self) -> _MutationScanLock:
        _, _, ms_lock = self._get_instance_locks()
        return ms_lock

    @contextlib.contextmanager
    def _operation_context(self, key):
        with self._get_key_lock(key):
            with super()._operation_context(key):
                yield

    def expand(self, key: Digest | str) -> Digest:
        with self._get_mutation_scan_lock().scan():
            return super().expand(key)

    def put(self, value: Any, key: Digest) -> Digest:
        with self._get_mutation_scan_lock().mutation():
            return super().put(value, key)

    def _evict(self, key: Digest) -> None:
        with self._get_mutation_scan_lock().mutation():
            super()._evict(key)

