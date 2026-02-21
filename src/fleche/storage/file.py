from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .base import CallStorage, Storage
from ..digest import Digest


@dataclass
class FileStorage(Storage):
    """File-based storage backend using pickle.

    Stores objects on the filesystem.
    """
    root: Path

    def __post_init__(self) -> None:
        self.root = Path(self.root).expanduser().absolute().resolve()

    def _path(self, key: str) -> Path:
        self.root.mkdir(parents=True, exist_ok=True)
        return self.root / key

    def list(self) -> Iterable[Digest]:
        self.root.mkdir(parents=True, exist_ok=True)
        return (Digest(p.name) for p in self.root.iterdir())

    def _evict(self, key: Digest) -> None:
        self._path(key).unlink(missing_ok=True)
