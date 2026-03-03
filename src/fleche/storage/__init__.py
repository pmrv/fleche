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
    DestructuringStorage,
)
from .memory import Memory
from .void import Void
from .file import FileStorage
from .pickle_file import PickleFile, CloudpickleFile
from .bagofholding_file import BagOfHoldingH5File
from .sql import Sql

__all__ = [
    "SaveError",
    "AmbiguousDigestError",
    "Storage",
    "CallStorage",
    "CallStorageAdapter",
    "DestructuringStorage",
    "Memory",
    "Void",
    "FileStorage",
    "CloudpickleFile",
    "PickleFile",
    "BagOfHoldingH5File",
    "Sql",
]
