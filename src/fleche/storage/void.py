from dataclasses import dataclass
from typing import Any, Iterable

from .base import ValueMixin, CallMixin, StorageBackend, register_storage
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


@register_storage("void", kind="value")
@dataclass(frozen=True)
class ValueVoid(ValueMixin, VoidBackend):
    def to_config(self) -> dict[str, Any]:
        return {"type": "void"}

@register_storage("void", kind="call")
@dataclass(frozen=True)
class CallVoid(CallMixin, VoidBackend):
    def to_config(self) -> dict[str, Any]:
        return {"type": "void"}
