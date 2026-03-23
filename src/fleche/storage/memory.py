from dataclasses import dataclass
from typing import Any, Iterable

from .base import Storage
from .thread_safe import ThreadSafeMixin
from ..digest import Digest
from copy import deepcopy


@dataclass
class Memory(Storage):
    """
    A concrete implementation of Storage that stores values in an in-memory dictionary.
    """

    storage: dict[Digest, Any]

    def _save(self, value: Any, key: Digest) -> Digest:
        self.storage[key] = deepcopy(value)
        return key

    def _load(self, key: Digest) -> Any:
        return deepcopy(self.storage[key])

    def _contains(self, key: Digest) -> bool:
        return key in self.storage

    def list(self) -> Iterable[Digest]:
        return tuple(self.storage.keys())

    def _evict(self, key: Digest) -> None:
        self.storage.pop(key, None)


class MemoryThreadSafe(ThreadSafeMixin, Memory):
    """Thread-safe in-memory storage.

    All public operations (*save*, *load*, *contains*, *evict*, *list*) are
    serialised with a per-instance :class:`threading.RLock`.

    When passed to :class:`~fleche.caches.Cache` as both the value *and* call
    storage, ``Cache`` automatically wraps the call-storage side in a
    :class:`~fleche.storage.base.ThreadSafeCallStorageAdapter` so that the
    compound check-evict-save in
    :meth:`~fleche.storage.base.CallStorage.save` is also atomic::

        mem = MemoryThreadSafe({})
        cache = Cache(mem, mem)   # fully thread-safe
    """
