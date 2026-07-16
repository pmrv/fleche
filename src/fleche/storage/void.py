from dataclasses import dataclass
from typing import Any, Iterable

from .base import ValueMixin, CallMixin, StorageBackend
from ..digest import Digest


@dataclass(frozen=True)
class VoidBackend(StorageBackend):
    """
    A concrete implementation of Storage that does not store anything.
    """

    def put(self, value: Any, key: Digest) -> Digest:
        return key

    def get(self, key: Digest) -> Any:
        raise KeyError(key)

    def list(self) -> Iterable[Digest]:
        return ()

    def _evict(self, key: Digest) -> None:
        pass

    def _contains(self, key: Digest) -> bool:
        return False


@dataclass(frozen=True)
class ValueVoid(ValueMixin, VoidBackend): ...

@dataclass(frozen=True)
class CallVoid(CallMixin, VoidBackend): ...
