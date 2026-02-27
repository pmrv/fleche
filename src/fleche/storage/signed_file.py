from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from .file import FileStorage
from ..digest import Digest
from ..security import get_secret_key, sign, verify

logger = logging.getLogger("fleche.storage.signed_file")

@dataclass
class SignedFileStorage(FileStorage):
    """
    Abstract base class for file storages that support signing.
    """
    secret_key: bytes | None = None

    def __post_init__(self):
        super().__post_init__()
        if self.secret_key is None:
            self.secret_key = get_secret_key()

    def _write_signed(self, key: Digest, data: bytes) -> None:
        """Helper to write signed data."""
        signature = sign(data, self.secret_key)
        (self._path(key)).write_bytes(signature + data)

    def _read_signed(self, key: Digest) -> bytes:
        """Helper to read and verify signed data."""
        try:
            content = (self._path(key)).read_bytes()

            # If no secret key is configured, treat the whole content as data (legacy/unsigned mode)
            # OR we can enforce that if a key is present, a signature MUST be present.
            # The previous logic was: if key is present, verify.
            # If key is None (noop mode), verify returns True.

            if self.secret_key is None:
                # In no-op mode, we just return the content.
                # HOWEVER, if we wrote it in no-op mode, sign() returned b"", so content is just data.
                return content

            if len(content) < 32:
                 # Too short to contain a signature
                 logger.warning("Cache entry %s too short to be valid signed data.", key)
                 raise KeyError(key)

            signature = content[:32]
            data = content[32:]

            if not verify(data, signature, self.secret_key):
                logger.warning("Invalid signature for cache entry %s. Potential tampering or key mismatch.", key)
                raise KeyError(key)

            return data
        except FileNotFoundError:
            raise KeyError(key) from None
