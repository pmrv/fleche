"""Thread-safety mixin for Storage and CallStorage classes."""

import threading
from typing import Any, Iterable


class ThreadSafeMixin:
    """Mixin that serialises all public storage operations with a per-instance RLock.

    Wrapping *save*, *load*, *contains*, *evict*, and *list* with a reentrant
    lock has two useful properties:

    1. Individual dict / file operations become atomic even when multiple
       threads share the same storage object.
    2. When the mixin is applied to a :class:`~fleche.storage.base.CallStorage`
       subclass the *compound* check-evict-save sequence in
       ``CallStorage.save()`` becomes fully atomic, because the outer
       ``ThreadSafeMixin.save()`` call holds the lock for the whole duration
       of ``super().save()``, and the inner calls to ``contains()`` and
       ``evict()`` simply re-acquire the same RLock reentrantly.

    The lock is created lazily (on first access) so that it is never part of
    the object's pickle payload; it is recreated transparently after
    unpickling.

    Usage::

        class MyThreadSafeStorage(ThreadSafeMixin, MyStorage):
            pass

        mem = MemoryThreadSafe({})          # value storage
        calls = ThreadSafeCallStorageAdapter(mem)  # call storage
    """

    @property
    def _lock(self) -> threading.RLock:
        """Per-instance reentrant lock, created lazily."""
        try:
            return object.__getattribute__(self, "_ts_lock")
        except AttributeError:
            lock = threading.RLock()
            # object.__setattr__ bypasses frozen-dataclass restrictions and
            # writes directly into __dict__ (available because this mixin does
            # not define __slots__).
            object.__setattr__(self, "_ts_lock", lock)
            return lock

    # ------------------------------------------------------------------
    # Public API overrides – each acquires the lock before delegating
    # ------------------------------------------------------------------

    def save(self, *args: Any, **kwargs: Any) -> Any:
        with self._lock:
            return super().save(*args, **kwargs)  # type: ignore[misc]

    def load(self, *args: Any, **kwargs: Any) -> Any:
        with self._lock:
            return super().load(*args, **kwargs)  # type: ignore[misc]

    def contains(self, *args: Any, **kwargs: Any) -> bool:
        with self._lock:
            return super().contains(*args, **kwargs)  # type: ignore[misc]

    def evict(self, *args: Any, **kwargs: Any) -> None:
        with self._lock:
            super().evict(*args, **kwargs)  # type: ignore[misc]

    def list(self) -> Iterable:
        with self._lock:
            return super().list()  # type: ignore[misc]

    # ------------------------------------------------------------------
    # Pickle support – exclude the (non-picklable) lock
    # ------------------------------------------------------------------

    def __getstate__(self) -> dict:
        state = self.__dict__.copy()
        state.pop("_ts_lock", None)
        return state

    def __setstate__(self, state: dict) -> None:
        self.__dict__.update(state)
