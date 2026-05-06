from dataclasses import dataclass
from typing import Any, Iterable

from .base import ValueMixin, CallMixin, StorageBackend
from .destructuring import DestructuringMixin
from ..digest import Digest
from copy import deepcopy


@dataclass(frozen=True)
class MemoryBackend(StorageBackend):
    """
    A concrete implementation of Storage that stores values in an in-memory dictionary.
    """

    storage: dict[Digest, Any]

    # Each storage instance is its own world: hash on identity so that frozen
    # dataclass subclasses can serve as WeakKeyDictionary keys in PerKeyLockMixin
    # without the unhashable dict field causing a TypeError.
    __hash__ = object.__hash__

    def list(self) -> Iterable[Digest]:
        return tuple(self.storage.keys())

    def put(self, value: Any, key: Digest) -> Digest:
        self.storage[key] = deepcopy(value)
        return key

    def get(self, key: Digest) -> Any:
        return deepcopy(self.storage[key])

    def _contains(self, key: Digest) -> bool:
        return key in self.storage

    def _evict(self, key: Digest) -> None:
        self.storage.pop(key, None)


@dataclass(frozen=True)
class ValueMemory(DestructuringMixin, ValueMixin, MemoryBackend):
    __hash__ = object.__hash__

@dataclass(frozen=True)
class CallMemory(CallMixin, MemoryBackend):
    __hash__ = object.__hash__
