"""Storage subpackage public API.

This module re-exports the primary storage interfaces and implementations
for backward compatibility with `from fleche.storage import ...` imports.
"""

from .base import (
    SaveError,
    AmbiguousDigestError,
    Storage,
    CallStorage,
    CallStorageAdapter,
    DestructuringMixin,
    DestructuringStorage,
)
from .memory import Memory
from .void import Void
from .file import FileStorage
from .pickle_file import PickleFile
from .bagofholding_file import BagOfHoldingH5File
from .sql import Sql

__all__ = [
    "SaveError",
    "AmbiguousDigestError",
    "Storage",
    "CallStorage",
    "CallStorageAdapter",
    "DestructuringMixin",
    "DestructuringStorage",
    "Memory",
    "Void",
    "FileStorage",
    "PickleFile",
    "BagOfHoldingH5File",
    "Sql",
]
