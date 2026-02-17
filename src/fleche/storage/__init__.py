"""Storage subpackage public API.

This module re-exports the primary storage interfaces and implementations
for backward compatibility with `from fleche.storage import ...` imports.
"""

from .base import SaveError, AmbiguousDigestError, Storage, CallStorage
from .memory import Memory
from .file import FileStorage
from .cloudpickle_file import CloudpickleFile
from .pickle_file import PickleFile
from .bagofholding_file import BagOfHoldingH5File
from .sql import Sql

__all__ = [
    "SaveError",
    "AmbiguousDigestError",
    "Storage",
    "CallStorage",
    "Memory",
    "FileStorage",
    "CloudpickleFile",
    "PickleFile",
    "BagOfHoldingH5File",
    "Sql",
]
