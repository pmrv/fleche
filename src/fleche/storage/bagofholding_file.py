from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from bagofholding import H5Bag

from .file import FileStorage
from .base import SaveError
from ..digest import Digest

@dataclass
class BagOfHoldingH5File(FileStorage):

    def _save(self, value: Any, key: Digest) -> str:
        try:
            H5Bag.save(value, self._path(key))
        except (ValueError, TypeError):  # h5py choked on something, pass it along
            raise SaveError(value) from None
        return key

    def _load(self, key: str) -> Any:
        try:
            return H5Bag(self._path(key)).load()
        except FileNotFoundError:
            raise KeyError(key) from None
