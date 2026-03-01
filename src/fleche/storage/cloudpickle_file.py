from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from cloudpickle import loads, dumps

from .file import FileStorage
from ..digest import Digest
from ..security import get_secret_key, SignedBytes, SignatureError

logger = logging.getLogger("fleche.storage.cloudpickle_file")

@dataclass
class CloudpickleFile(FileStorage):
    """
    Store values as files on the filesystem using cloudpickle for serialization.
    """
    secret_key: list[bytes] | bytes | None = None

    def __post_init__(self):
        super().__post_init__()
        if self.secret_key is None:
            self.secret_key = get_secret_key()

    def _save(self, value: Any, key: Digest) -> Digest:
        signer = SignedBytes(self.secret_key)
        data = signer.dumps(dumps(value))
        (self._path(key)).write_bytes(data)
        return key

    def _load(self, key: Digest) -> Any:
        try:
            content = (self._path(key)).read_bytes()
            signer = SignedBytes(self.secret_key)
            data = signer.loads(content)
            return loads(data)
        except FileNotFoundError:
            raise KeyError(key) from None
        except SignatureError:
            raise KeyError(key, "Value present but failed signature check.")
