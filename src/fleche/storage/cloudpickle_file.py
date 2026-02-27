from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from cloudpickle import loads, dumps

from .file import FileStorage
from .signed_file import SignedFileStorage
from ..digest import Digest

@dataclass
class CloudpickleFile(SignedFileStorage):
    """
    Store values as files on the filesystem using cloudpickle for serialization.
    """
    def _save(self, value: Any, key: Digest) -> Digest:
        data = dumps(value)
        self._write_signed(key, data)
        return key

    def _load(self, key: Digest) -> Any:
        try:
            data = self._read_signed(key)
            return loads(data)
        except FileNotFoundError:
            raise KeyError(key) from None
