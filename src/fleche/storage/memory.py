from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from .base import Storage, CallStorage
from ..digest import Digest
from copy import deepcopy


@dataclass
class Memory(CallStorage, Storage):
    """
    A concrete implementation of Storage that stores values in an in-memory dictionary.
    """

    storage: dict[str, Any]

    def _save(self, value: Any, key: Digest) -> str:
        if key in self.storage:
            return key
        self.storage[key] = deepcopy(value)
        return key

    def _load(self, key: str) -> Any:
        return deepcopy(self.storage[key])

    def list(self) -> Iterable[str]:
        return self.storage.keys()

    def _evict(self, key: str) -> None:
        self.storage.pop(key, None)
