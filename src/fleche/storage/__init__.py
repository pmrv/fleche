"""Storage subpackage public API.

This module re-exports the primary storage interfaces and implementations
for backward compatibility with `from fleche.storage import ...` imports.
"""

from .base import (
    SaveError,
    AmbiguousDigestError,
    KeyManagement,
    StorageBackend,
    ValueStorage,
    ValueMixin,
    CallStorage,
    CallMixin,
)
from .destructuring import DestructuringMixin
from .memory import ValueMemory, CallMemory
from .void import ValueVoid, CallVoid
from .file import FileStorage
from .pickle_file import ValuePickleFile, CallPickleFile
from .bagofholding_file import ValueBagOfHoldingH5File, CallBagOfHoldingH5File
from .sql import Sql
from .thread_safe import SerializingMixin, PerKeyLockMixin

__all__ = [
    "SaveError",
    "AmbiguousDigestError",
    "KeyManagement",
    "StorageBackend",
    "ValueStorage",
    "ValueMixin",
    "CallStorage",
    "CallMixin",
    "DestructuringMixin",
    "ValueMemory",
    "CallMemory",
    "ValueVoid",
    "CallVoid",
    "FileStorage",
    "ValuePickleFile",
    "CallPickleFile",
    "ValueBagOfHoldingH5File",
    "CallBagOfHoldingH5File",
    "Sql",
    "SerializingMixin",
    "PerKeyLockMixin",
]
