from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Any

from .base import CallStorage, Storage, DIGEST_LENGTH
from ..digest import Digest, digest

logger = logging.getLogger("fleche.storage")


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
        return (Digest(p.name) for p in self.root.iterdir() if not p.name.endswith(".lock"))

    def _evict(self, key: Digest) -> None:
        self._path(key).unlink(missing_ok=True)
        (self.root / f"{key}.lock").unlink(missing_ok=True)

    def save(self, value: Any, key: Digest | None = None) -> Digest:
        if key is None:
            key = digest(value)

        lock_path = self.root / f"{key}.lock"
        self.root.mkdir(parents=True, exist_ok=True)
        lock_path.write_text(f"{os.getpid()}\n{time.time()}")
        try:
            return super().save(value, key)
        finally:
            lock_path.unlink(missing_ok=True)

    def load(self, key: Digest | str) -> Any:
        if len(key) < DIGEST_LENGTH:
            key = self.expand(key)
        else:
            key = Digest(key)

        lock_path = self.root / f"{key}.lock"
        tried_anyway = False
        if lock_path.exists():
            start_time = time.perf_counter()
            wait_time = self.lock_wait_start
            while lock_path.exists() and (time.perf_counter() - start_time) < self.lock_timeout:
                time.sleep(wait_time)
                wait_time *= 2

            if lock_path.exists():
                logger.warning("Lock still held for %s after %s seconds, trying to read anyway.", key, self.lock_timeout)
                tried_anyway = True

        try:
            return super().load(key)
        except Exception as e:
            if tried_anyway:
                logger.error("Failed to read %s after timeout while lock was held: %s", key, e)
                raise KeyError(key) from None
            raise
