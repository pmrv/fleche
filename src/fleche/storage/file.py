from abc import abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Any, Callable
from uuid import uuid4

from .base import StorageBackend
from ..digest import Digest


def _atomic_write(path: Path, write: Callable[[Path], Any]) -> None:
    """Have *write* produce a sibling temp file, then rename it over *path*.

    ``os.replace`` is atomic on POSIX for paths on the same filesystem, so
    readers observe either the previous complete file or the new complete
    file, never a partial write.  The temp name is dot-prefixed so ``list()``
    and the bagofholding layout scan never pick it up, and *write* (rather
    than e.g. ``mkstemp``) creates the file so the usual umask applies —
    shared caches stay readable for other users.
    """
    tmp = path.parent / f".{path.name}.{uuid4().hex}.tmp"
    try:
        write(tmp)
        tmp.replace(path)
    finally:
        tmp.unlink(missing_ok=True)


@dataclass(frozen=True)
class FileStorage(StorageBackend):
    """File-based storage backend, one file per key.

    Stores objects on the filesystem.  Writes go to a temporary file that is
    atomically renamed into place, so concurrent readers never observe a
    partially written entry and no cross-process locking is needed —
    ``_to_file`` must therefore write a complete file at the path it is given,
    which may be a temporary sibling of the entry's final path.

    ``lock_timeout`` is unused here: file locking was dropped in favour of
    atomic renames because the ``filelock`` package never removes its
    ``{key}.lock`` files on Unix, doubling the inode footprint of a cache
    (and thereby filesystem quota usage).  The field is retained so configs
    and call sites passing it keep working, and for subclasses that genuinely
    need cross-process locking (in-place mutation of shared files, e.g.
    :class:`~fleche.storage.bagofholding_file.BagOfHoldingH5FileBackend`).
    """

    root: Path
    lock_timeout: float = 1.0

    def __post_init__(self) -> None:
        object.__setattr__(self, "root", Path(self.root).expanduser().absolute().resolve())

    def _path(self, key: str) -> Path:
        self.root.mkdir(parents=True, exist_ok=True)
        return self.root / key

    def list(self) -> Iterable[Digest]:
        # ".lock" files linger in caches written by fleche < 2.1; dot-files
        # cover in-flight atomic-write temp files (and are good hygiene).
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
        # fleche < 2.1 left a lock file next to every entry; clean it up with
        # the entry so old caches shrink back over time.
        self._path(f"{key}.lock").unlink(missing_ok=True)

    def put(self, value: Any, key: Digest) -> Digest:
        _atomic_write(self._path(key), lambda tmp: self._to_file(value, tmp))
        return key

    def get(self, key: Digest) -> Any:
        return self._from_file(self._path(key))

    @abstractmethod
    def _to_file(self, value: Any, path: Path) -> None: ...

    @abstractmethod
    def _from_file(self, path: Path) -> Any: ...

    def _contains(self, key: Digest) -> bool:
        return self._path(key).exists()
