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


@dataclass(frozen=True)
class SerializingMixin(KeyManagement):
    """Mixin that serializes all storage operations behind a single reentrant lock.

    Place before the concrete storage class in the MRO::

        @dataclass(frozen=True)
        class SerializingValueMemory(SerializingMixin, ValueMemory): ...
    """

    _lock: threading.RLock = field(
        default_factory=threading.RLock, init=False, repr=False, compare=False
    )

    @contextlib.contextmanager
    def _operation_context(self, key):
        with self._lock:
            with super()._operation_context(key):
                yield


@dataclass(frozen=True)
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

    _key_locks: weakref.WeakValueDictionary[Digest | str, threading.RLock] = field(
        default_factory=weakref.WeakValueDictionary, init=False, repr=False, compare=False
    )
    _meta_lock: threading.Lock = field(
        default_factory=threading.Lock, init=False, repr=False, compare=False
    )

    def _get_key_lock(self, key: Digest | str) -> threading.RLock:
        with self._meta_lock:
            # Hold a strong reference so the lock is not collected between
            # creation and return — WeakValueDictionary only stores a weak ref.
            lock = self._key_locks.get(key)
            if lock is None:
                lock = threading.RLock()
                self._key_locks[key] = lock
            return lock

    @contextlib.contextmanager
    def _operation_context(self, key):
        with self._get_key_lock(key):
            with super()._operation_context(key):
                yield

