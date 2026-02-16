from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from .base import Storage, CallStorage
from ..digest import digest, Digest, DIGEST_LENGTH
from copy import deepcopy


@dataclass
class Memory(CallStorage, Storage):
    """
    A concrete implementation of Storage that stores values in an in-memory dictionary.
    """

    storage: dict[str, Any]

    def save(self, value: Any, key: Digest | None = None) -> str:
        if key is None:
            key = digest(value)
        if key in self.storage:
            return key
        self.storage[key] = deepcopy(value)
        return key

    def load(self, key: str) -> Any:
        if len(key) < DIGEST_LENGTH:
            key = self.expand(key)
        return deepcopy(self.storage[key])

    def list(self) -> Iterable[str]:
        return self.storage.keys()
