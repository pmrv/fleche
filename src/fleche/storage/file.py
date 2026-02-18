from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .base import CallStorage, Storage


@dataclass
class FileStorage(CallStorage, Storage):
    """File-based storage backend using pickle.

    Stores objects on the filesystem.
    """
    root: Path

    def __post_init__(self) -> None:
        self.root = Path(self.root).expanduser().absolute().resolve()

    def _path(self, key: str) -> Path:
        self.root.mkdir(parents=True, exist_ok=True)
        return self.root / key

    def list(self) -> Iterable[str]:
        self.root.mkdir(parents=True, exist_ok=True)
        return (p.name for p in self.root.iterdir())

    def _evict(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)
