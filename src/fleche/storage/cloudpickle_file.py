from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from cloudpickle import loads, dumps

from .file import FileStorage
from ..digest import digest, Digest, DIGEST_LENGTH


@dataclass
class CloudpickleFile(FileStorage):
    """
    Store values as files on the filesystem using cloudpickle for serialization.
    """

    def save(self, value: Any, key: Digest | None = None) -> str:
        if key is None:
            key = digest(value)
        (self._path(key)).write_bytes(dumps(value))
        return key

    def load(self, key: str) -> Any:
        if len(key) < DIGEST_LENGTH:
            key = self.expand(key)
        try:
            return loads((self._path(key)).read_bytes())
        except FileNotFoundError:
            raise KeyError(key) from None
