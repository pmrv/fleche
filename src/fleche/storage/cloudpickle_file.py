from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from cloudpickle import loads, dumps

from .file import FileStorage
from ..digest import Digest


@dataclass
class CloudpickleFile(FileStorage):
    """
    Store values as files on the filesystem using cloudpickle for serialization.
    """

    def _save(self, value: Any, key: Digest) -> Digest:
        (self._path(key)).write_bytes(dumps(value))
        return key

    def _load(self, key: Digest) -> Any:
        try:
            return loads((self._path(key)).read_bytes())
        except FileNotFoundError:
            raise KeyError(key) from None
