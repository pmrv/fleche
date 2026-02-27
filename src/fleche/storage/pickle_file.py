from __future__ import annotations

import pickle
import logging
from dataclasses import dataclass
from typing import Any

from .file import FileStorage
from ..digest import Digest
from ..security import get_secret_key, sign, verify

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
        data = pickle.dumps(value)
        signature = sign(data, self.secret_key)
        (self._path(key)).write_bytes(signature + data)
        return key

    def _load(self, key: Digest) -> Any:
        try:
            content = (self._path(key)).read_bytes()
            if len(content) < 32:
                 # Too short to contain a signature
                 logger.warning("Cache entry %s too short to be valid signed data.", key)
                 raise KeyError(key)

            signature = content[:32]
            data = content[32:]

            if not verify(data, signature, self.secret_key):
                logger.warning("Invalid signature for cache entry %s. Potential tampering or key mismatch.", key)
                raise KeyError(key)

            return pickle.loads(data)
        except FileNotFoundError:
            raise KeyError(key) from None
