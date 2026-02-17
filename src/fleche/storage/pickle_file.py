from __future__ import annotations

import pickle
from dataclasses import dataclass
from typing import Any

from .file import FileStorage
from ..digest import digest, Digest, DIGEST_LENGTH


@dataclass
class PickleFile(FileStorage):
    """
    Store values as files on the filesystem using the standard pickle module for serialization.
    """

    def save(self, value: Any, key: Digest | None = None) -> str:
        if key is None:
            key = digest(value)
        (self._path(key)).write_bytes(pickle.dumps(value))
        return key

    def load(self, key: str) -> Any:
        if len(key) < DIGEST_LENGTH:
            key = self.expand(key)
        try:
            return pickle.loads((self._path(key)).read_bytes())
        except FileNotFoundError:
            raise KeyError(key) from None
