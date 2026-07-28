from dataclasses import dataclass
from typing import Any, ClassVar, Iterable

from .base import ValueMixin, CallMixin, StorageBackend, register_storage
from .destructuring import DestructuringMixin
from .thread_safe import PerKeyLockMixin
from ..digest import Digest
from copy import deepcopy


@dataclass(frozen=True)
class MemoryBackend(StorageBackend):
    """
    A concrete implementation of Storage that stores values in an in-memory dictionary.
    """

    storage: dict[Digest, Any]

    # The live store is runtime state, not configuration; from_config seeds a
    # fresh one instead.
    _config_exclude: ClassVar[tuple[str, ...]] = ("storage",)

    # Each storage instance is its own world: hash on identity so that frozen
    # dataclass subclasses can serve as WeakKeyDictionary keys in PerKeyLockMixin
    # without the indigestible dict field causing a TypeError.
    __hash__ = object.__hash__

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        if "__hash__" not in cls.__dict__:
            raise TypeError(
                f"{cls.__qualname__} subclasses MemoryBackend without defining "
                "`__hash__ = object.__hash__`. The inherited `storage: dict` field is "
                "unhashable, and `@dataclass(frozen=True)` regenerates `__hash__` on "
                "every subclass without carrying the override through. "
                "Add `__hash__ = object.__hash__` to the class body."
            )

    def list(self) -> Iterable[Digest]:
        return tuple(self.storage.keys())

    def put(self, value: Any, key: Digest) -> Digest:
        self.storage[key] = deepcopy(value)
        return key

    def get(self, key: Digest) -> Any:
        return deepcopy(self.storage[key])

    def _contains(self, key: Digest) -> bool:
        return key in self.storage

    def _evict(self, key: Digest) -> None:
        self.storage.pop(key, None)

    @classmethod
    def from_config(cls, **kwargs) -> "MemoryBackend":
        """Alternate constructor for ``storage_from_config``.

        The config carries no ``storage`` dict (it's runtime state, not
        configuration), so seed a fresh empty one.
        """
        return cls({}, **kwargs)


@dataclass(frozen=True)
class ValueMemory(PerKeyLockMixin, DestructuringMixin, ValueMixin, MemoryBackend):
    __hash__ = object.__hash__

register_storage("memory", kind="value", factory=ValueMemory.from_config)(ValueMemory)


@dataclass(frozen=True)
class CallMemory(PerKeyLockMixin, CallMixin, MemoryBackend):
    __hash__ = object.__hash__

register_storage("memory", kind="call", factory=CallMemory.from_config)(CallMemory)
