from __future__ import annotations

import pickle
import logging
from dataclasses import dataclass
from typing import Any

from .file import FileStorage
from .signed_file import SignedFileStorage
from ..digest import Digest

@dataclass
class PickleFile(SignedFileStorage):
    """
    Store values as files on the filesystem using the standard pickle module for serialization.
    """

    def _save(self, value: Any, key: Digest) -> Digest:
        data = pickle.dumps(value)
        self._write_signed(key, data)
        return key

    def _load(self, key: Digest) -> Any:
        try:
            data = self._read_signed(key)
            return pickle.loads(data)
        except FileNotFoundError:
            raise KeyError(key) from None
