"""Storage subpackage public API.

This module re-exports the primary storage interfaces and implementations
for backward compatibility with `from fleche.storage import ...` imports.
"""

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
from .destructuring import (
    DestructuringMixin,
    HasChildDigests,
    HasScannableDigests,
    register_destructurer,
)
from .scan import ScanUnsupported, scan_h5, scan_pickle
from .memory import MemoryBackend, ValueMemory, CallMemory
from .void import VoidBackend, ValueVoid, CallVoid
from .file import FileStorage
from .pickle_file import PickleFileBackend, ValuePickleFile, CallPickleFile
from .bagofholding_file import (
    BagOfHoldingH5FileBackend,
    ValueBagOfHoldingH5File,
    CallBagOfHoldingH5File,
)
from .sql import Sql
from .thread_safe import SerializingMixin, PerKeyLockMixin

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
    "HasChildDigests",
    "HasScannableDigests",
    "register_destructurer",
    "ScanUnsupported",
    "scan_pickle",
    "scan_h5",
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
