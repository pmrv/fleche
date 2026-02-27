from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .file import FileStorage
from ..digest import Digest

try:
    from pyiron_snippets.import_alarm import ImportAlarm
except ImportError:
    # Fallback if pyiron-snippets is not available
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
    "CloudpickleFile requires 'cloudpickle' to be installed. "
    "Install it with `pip install fleche[cloudpickle]`.",
    raise_exception=True
) as cloudpickle_alarm:
    from cloudpickle import loads, dumps


@dataclass
class CloudpickleFile(FileStorage):
    """
    Store values as files on the filesystem using cloudpickle for serialization.
    """

    @cloudpickle_alarm
    def __post_init__(self):
        if hasattr(super(), "__post_init__"):
            super().__post_init__()

    def _save(self, value: Any, key: Digest) -> Digest:
        (self._path(key)).write_bytes(dumps(value))
        return key

    def _load(self, key: Digest) -> Any:
        try:
            return loads((self._path(key)).read_bytes())
        except FileNotFoundError:
            raise KeyError(key) from None
