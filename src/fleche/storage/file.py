import logging
import os
import socket
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Any, Generator

from .base import Storage, DIGEST_LENGTH
from ..digest import Digest, digest

logger = logging.getLogger("fleche.storage")


@contextmanager
def file_write_lock(lock_path: Path) -> Generator[None, None, None]:
    """Context manager for acquiring a write lock on a file.

    Creates a lock file with hostname, PID, and timestamp.
    """
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.write_text(f"{socket.gethostname()}\n{os.getpid()}\n{time.time()}")
    try:
        yield
    finally:
        lock_path.unlink(missing_ok=True)


@contextmanager
def file_read_lock(
    lock_path: Path, timeout: float, wait_start: float, key: str
) -> Generator[None, None, None]:
    """Context manager for acquiring a read lock on a file.

    Waits for a lock file to be removed with exponential backoff.
    """
    tried_anyway = False
    if lock_path.exists():
        start_time = time.perf_counter()
        wait_time = wait_start
        while lock_path.exists() and (time.perf_counter() - start_time) < timeout:
            time.sleep(wait_time)
            wait_time *= 2

        if lock_path.exists():
            try:
                lock_info = lock_path.read_text().replace("\n", " ")
            except Exception:
                lock_info = "unknown"
            logger.warning(
                "Lock still held for %s after %s seconds (info: %s), trying to read anyway.",
                key,
                timeout,
                lock_info,
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


@dataclass
class FileStorage(Storage):
    """File-based storage backend using pickle.

    Stores objects on the filesystem.
    """

    root: Path
    lock_timeout: float = 1.0
    lock_wait_start: float = 0.001

    def __post_init__(self) -> None:
        self.root = Path(self.root).expanduser().absolute().resolve()

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

    def save(self, value: Any, key: Digest | None = None) -> Digest:
        if key is None:
            key = digest(value)

        lock_path = self._path(f"{key}.lock")
        with file_write_lock(lock_path):
            return super().save(value, key)

    def load(self, key: Digest | str) -> Any:
        if len(key) < DIGEST_LENGTH:
            key = self.expand(key)
        else:
            key = Digest(key)

        lock_path = self._path(f"{key}.lock")
        with file_read_lock(
            lock_path, self.lock_timeout, self.lock_wait_start, str(key)
        ):
            return super().load(key)

    def _contains(self, key: Digest) -> bool:
        return self._path(key).exists()
