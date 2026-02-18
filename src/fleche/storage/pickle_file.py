from __future__ import annotations

import pickle
from dataclasses import dataclass
from typing import Any

from .file import FileStorage
from ..digest import Digest


@dataclass
class PickleFile(FileStorage):
    """
    Store values as files on the filesystem using the standard pickle module for serialization.
    """

    def _save(self, value: Any, key: Digest) -> str:
        (self._path(key)).write_bytes(pickle.dumps(value))
        return key

    def _load(self, key: str) -> Any:
        try:
            return pickle.loads((self._path(key)).read_bytes())
        except FileNotFoundError:
            raise KeyError(key) from None
