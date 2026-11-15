"""Storage subpackage public API.

This module re-exports the primary storage interfaces and implementations
for backward compatibility with `from fleche.storage import ...` imports.

:class:`~fleche.storage.sql.Sql` is the exception: it and its module,
``fleche.storage.sql``, are imported on first access, so that ``import fleche``
does not import SQLAlchemy for everyone who has it installed but never uses it.
"""

import importlib
from typing import TYPE_CHECKING

from .base import (
    SaveError,
    AmbiguousDigestError,
    Intent,
    OperationContext,
    KeyManagement,
    StorageBackend,
    ValueStorage,
    ValueMixin,
    CallStorage,
    CallMixin,
    register_storage,
    get_storage_constructor,
    is_registered_storage,
)
from .destructuring import DestructuringMixin, register_destructurer
from .memory import MemoryBackend, ValueMemory, CallMemory
from .void import VoidBackend, ValueVoid, CallVoid
from .file import FileStorage
from .pickle_file import PickleFileBackend, ValuePickleFile, CallPickleFile
from .bagofholding_file import (
    BagOfHoldingH5FileBackend,
    ValueBagOfHoldingH5File,
    CallBagOfHoldingH5File,
)
from .thread_safe import SerializingMixin, PerKeyLockMixin

if TYPE_CHECKING:
    from .sql import Sql


def __getattr__(name: str):
    if name == "Sql":
        from .sql import Sql

        return Sql
    if name == "sql":
        return importlib.import_module(".sql", __name__)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(set(globals()) | {"Sql", "sql"})


__all__ = [
    "SaveError",
    "AmbiguousDigestError",
    "Intent",
    "OperationContext",
    "KeyManagement",
    "StorageBackend",
    "ValueStorage",
    "ValueMixin",
    "CallStorage",
    "CallMixin",
    "register_storage",
    "get_storage_constructor",
    "is_registered_storage",
    "DestructuringMixin",
    "register_destructurer",
    "MemoryBackend",
    "ValueMemory",
    "CallMemory",
    "VoidBackend",
    "ValueVoid",
    "CallVoid",
    "FileStorage",
    "PickleFileBackend",
    "ValuePickleFile",
    "CallPickleFile",
    "BagOfHoldingH5FileBackend",
    "ValueBagOfHoldingH5File",
    "CallBagOfHoldingH5File",
    "Sql",
    "SerializingMixin",
    "PerKeyLockMixin",
]
