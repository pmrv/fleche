import pickle
import logging
import gzip
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .file import FileStorage, file_write_lock
from .base import ValueMixin, CallMixin
from .thread_safe import PerKeyLockMixin
from .destructuring import DestructuringMixin
from ..security import get_secret_key, normalize_secret_key, SignedBytes, SignatureError

from pyiron_snippets.import_alarm import ImportAlarm

logger = logging.getLogger("fleche.storage.pickle_file")

with ImportAlarm(
    "PickleFile.with_cloudpickle requires 'cloudpickle' to be installed. "
    "Install it with `pip install fleche[cloudpickle]`.",
    raise_exception=True,
) as cloudpickle_alarm:
    import cloudpickle

with ImportAlarm(
    "PickleFile.with_dill requires 'dill' to be installed. "
    "Install it with `pip install fleche[dill]`.",
    raise_exception=True,
) as dill_alarm:
    import dill


@dataclass(frozen=True, kw_only=True)
class PickleFileBackend(FileStorage):
    """
    Store values as files on the filesystem using a serialization module.
    """

    secret_key: tuple[bytes, ...] = field(default_factory=tuple)
    dumps: Callable = field(repr=False)
    loads: Callable = field(repr=False)
    compress: bool = False

    def __post_init__(self):
        super().__post_init__()
        raw = get_secret_key() if not self.secret_key else normalize_secret_key(self.secret_key)
        object.__setattr__(self, "secret_key", tuple(raw))

    @classmethod
    def with_pickle(cls, *args, **kwargs):
        """Construct a PickleFileBackend using the standard pickle module."""
        return cls(*args, dumps=pickle.dumps, loads=pickle.loads, **kwargs)

    @classmethod
    @cloudpickle_alarm
    def with_cloudpickle(cls, *args, **kwargs):
        """Construct a PickleFileBackend using the cloudpickle module."""
        return cls(*args, dumps=cloudpickle.dumps, loads=cloudpickle.loads, **kwargs)

    @classmethod
    @dill_alarm
    def with_dill(cls, *args, **kwargs):
        """Construct a PickleFileBackend using the dill module."""
        return cls(*args, dumps=dill.dumps, loads=dill.loads, **kwargs)

    def _to_file(self, value: Any, path: Path) -> None:
        signer = SignedBytes(self.secret_key)
        data = signer.dumps(self.dumps(value))
        if self.compress:
            data = gzip.compress(data)
        path.write_bytes(data)

    def _from_file(self, path: Path) -> Any:
        try:
            content = path.read_bytes()
            if content[:2] == b"\x1f\x8b":
                content = gzip.decompress(content)
            signer = SignedBytes(self.secret_key)
            data = signer.loads(content)
            return self.loads(data)
        except FileNotFoundError:
            raise KeyError(path) from None
        except SignatureError:
            raise KeyError(path, "Value present but failed signature check.")

    def compress_all(self) -> None:
        """Rewrite all stored files in gzip-compressed form."""
        for key in list(self.list()):
            path = self._path(key)
            lock_path = self._path(f"{key}.lock")
            with file_write_lock(lock_path):
                try:
                    content = path.read_bytes()
                except FileNotFoundError:
                    continue
                if content[:2] != b"\x1f\x8b":
                    path.write_bytes(gzip.compress(content))

    def decompress_all(self) -> None:
        """Rewrite all stored files in uncompressed form."""
        for key in list(self.list()):
            path = self._path(key)
            lock_path = self._path(f"{key}.lock")
            with file_write_lock(lock_path):
                try:
                    content = path.read_bytes()
                except FileNotFoundError:
                    continue
                if content[:2] == b"\x1f\x8b":
                    path.write_bytes(gzip.decompress(content))


@dataclass(frozen=True)
class ValuePickleFile(PerKeyLockMixin, ValueMixin, DestructuringMixin, PickleFileBackend): ...

@dataclass(frozen=True)
class CallPickleFile(PerKeyLockMixin, CallMixin, PickleFileBackend): ...
