from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from .base import Storage
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
