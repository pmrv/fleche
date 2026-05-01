import logging
import filelock
from abc import abstractmethod
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Any, Generator

from .base import StorageBackend
from ..digest import Digest

logger = logging.getLogger("fleche.storage")


@contextmanager
def _file_read_lock_with_fallback(
    lock_path: Path, timeout: float, key: str
) -> Generator[None, None, None]:
    lock = filelock.FileLock(lock_path, timeout=timeout)
    tried_anyway = False
    try:
        lock.acquire()
    except filelock.Timeout:
        logger.warning(
            "Lock still held for %s after %s seconds, trying to read anyway.",
            key,
            timeout,
        )
        tried_anyway = True
    try:
        yield
    except Exception as e:
        if tried_anyway:
            logger.error(
                "Failed to read %s after timeout while lock was held: %s",
                key,
                e,
            )
            raise KeyError(key) from None
        raise
    finally:
        if not tried_anyway:
            lock.release()


@dataclass(frozen=True)
class FileStorage(StorageBackend):
    """File-based storage backend using pickle.

    Stores objects on the filesystem.
    """

    root: Path
    lock_timeout: float = 1.0

    def __post_init__(self) -> None:
        object.__setattr__(self, "root", Path(self.root).expanduser().absolute().resolve())

    def _path(self, key: str) -> Path:
        self.root.mkdir(parents=True, exist_ok=True)
        return self.root / key

    def list(self) -> Iterable[Digest]:
        self.root.mkdir(parents=True, exist_ok=True)
        return (
            Digest(p.name)
            for p in self.root.iterdir()
            if not p.name.endswith(".lock")
            and not p.name.startswith(".")
            and p.is_file()
        )

    def _evict(self, key: Digest) -> None:
        self._path(key).unlink(missing_ok=True)
        self._path(f"{key}.lock").unlink(missing_ok=True)

    def put(self, value: Any, key: Digest) -> Digest:
        lock_path = self._path(f"{key}.lock")
        with filelock.FileLock(lock_path, timeout=self.lock_timeout):
            self._to_file(value, self._path(key))
        return key

    def get(self, key: Digest) -> Any:
        lock_path = self._path(f"{key}.lock")
        with _file_read_lock_with_fallback(lock_path, self.lock_timeout, str(key)):
            return self._from_file(self._path(key))

    @abstractmethod
    def _to_file(self, value: Any, path: Path) -> None: ...

    @abstractmethod
    def _from_file(self, path: Path) -> Any: ...

    def _contains(self, key: Digest) -> bool:
        return self._path(key).exists()
