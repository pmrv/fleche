from dataclasses import dataclass
from typing import Any, Iterable

from .base import Storage
from ..digest import Digest


@dataclass(frozen=True)
class Void(Storage):
    """
    A concrete implementation of Storage that does not store anything.
    """

    def _save(self, value: Any, key: Digest) -> Digest:
        return key

    def _load(self, key: Digest) -> Any:
        raise KeyError(key)

    def list(self) -> Iterable[Digest]:
        return ()

    def _evict(self, key: Digest) -> None:
        pass

    def _contains(self, key: Digest) -> bool:
        return False
