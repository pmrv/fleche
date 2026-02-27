from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .file import FileStorage
from .base import SaveError
from ..digest import Digest

try:
    from pyiron_snippets.import_alarm import ImportAlarm
except ImportError:
    class ImportAlarm:
        def __init__(self, message=None, raise_exception=False):
            self.message = message
            self.raise_exception = raise_exception
            self.failed = False
        def __enter__(self):
            return self
        def __exit__(self, exc_type, exc_val, exc_tb):
            if exc_type is not None and issubclass(exc_type, ImportError):
                self.failed = True
                return True
        def __call__(self, func):
            def wrapper(*args, **kwargs):
                if self.failed and self.message and self.raise_exception:
                    raise ImportError(self.message)
                return func(*args, **kwargs)
            return wrapper


with ImportAlarm(
    "BagOfHoldingH5File requires 'bagofholding' to be installed. "
    "Install it with `pip install fleche[bagofholding]`.",
    raise_exception=True
) as bagofholding_alarm:
    from bagofholding import H5Bag

@dataclass
class BagOfHoldingH5File(FileStorage):

    @bagofholding_alarm
    def __post_init__(self):
        if hasattr(super(), "__post_init__"):
            super().__post_init__()

    def _save(self, value: Any, key: Digest) -> str:
        try:
            H5Bag.save(value, self._path(key))
        except (ValueError, TypeError):  # h5py choked on something, pass it along
            raise SaveError(value) from None
        return key

    def _load(self, key: str) -> Any:
        try:
            return H5Bag(self._path(key)).load()
        except FileNotFoundError:
            raise KeyError(key) from None
