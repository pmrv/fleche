from __future__ import annotations

import pickle
import logging
from dataclasses import dataclass
from typing import Any

from .file import FileStorage
from ..digest import Digest
from ..security import get_secret_key, SignedBytes

logger = logging.getLogger("fleche.storage.pickle_file")

@dataclass
class PickleFile(FileStorage):
    """
    Store values as files on the filesystem using the standard pickle module for serialization.
    """
    secret_key: bytes | None = None

    def __post_init__(self):
        super().__post_init__()
        if self.secret_key is None:
            self.secret_key = get_secret_key()

    def _save(self, value: Any, key: Digest) -> Digest:
        signer = SignedBytes(self.secret_key)
        data = signer.dumps(pickle.dumps(value))
        (self._path(key)).write_bytes(data)
        return key

    def _load(self, key: Digest) -> Any:
        try:
            content = (self._path(key)).read_bytes()
            signer = SignedBytes(self.secret_key)
            data = signer.loads(content)
            return pickle.loads(data)
        except FileNotFoundError:
            raise KeyError(key) from None
