from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Iterable
import logging
import filelock

from .file import FileStorage
from .base import SaveError, ValueMixin, CallMixin
from .thread_safe import PerKeyLockMixin
from .destructuring import DestructuringMixin
from ..digest import Digest

from pyiron_snippets.import_alarm import ImportAlarm

logger = logging.getLogger("fleche.storage.bagofholding_file")

with ImportAlarm(
    "BagOfHoldingH5File requires 'bagofholding' to be installed. "
    "Install it with `pip install fleche[bagofholding]`.",
    raise_exception=True,
) as bagofholding_alarm:
    from bagofholding import H5Bag
    import h5py

VersionValidator = Literal["exact", "semantic-minor", "semantic-major", "none"]


@dataclass(frozen=True)
class BagOfHoldingH5FileBackend(FileStorage):
    version_validator: VersionValidator | None = None
    # When set, keys sharing the first `prefix_length` characters are multiplexed as
    # sibling groups (named by the full key) into one file at root/{prefix}.h5, instead
    # of each key getting its own file.  `None` keeps one file per key.
    prefix_length: int | None = 2

    @bagofholding_alarm
    def __post_init__(self):
        if hasattr(super(), "__post_init__"):
            super().__post_init__()

    def _to_file(self, value: Any, path: Path) -> None:
        try:
            H5Bag.save(value, path)
        except (ValueError, TypeError):  # h5py choked on something, pass it along
            raise SaveError(value) from None

    def _from_file(self, path: Path) -> Any:
        try:
            # _skip_load=True skips the constructor's _load_existing_bag_info() call,
            # which would otherwise open and close the file just to read bag metadata
            # before load() opens it a second time to read the actual payload.
            bag = H5Bag(path, _skip_load=True)
            if self.version_validator is not None:
                return bag.load(version_validator=self.version_validator)
            return bag.load()
        except (FileNotFoundError, KeyError):
            raise KeyError(path) from None
        except OSError as e:
            logger.error("Corrupt file present in cache at path %s: %s", path, e, exc_info=True)
            raise KeyError(path) from e

    def _bag_file(self, key: str) -> Path:
        """The HDF5 file backing `key` in multi-bag mode: ``root/{prefix}.h5``."""
        self.root.mkdir(parents=True, exist_ok=True)
        return self.root / f"{key[: self.prefix_length]}.h5"

    def _path(self, key: str) -> Path:
        """Path to hand to :class:`H5Bag`: the plain per-key file, or the
        composite ``file.h5/{key}`` group path in multi-bag mode."""
        if self.prefix_length is None:
            return super()._path(key)
        return self._bag_file(key) / key

    def _lock_path(self, key: str) -> Path:
        if self.prefix_length is None:
            return super()._lock_path(key)
        return Path(f"{self._bag_file(key)}.lock")

    def _contains(self, key: Digest) -> bool:
        if self.prefix_length is None:
            return super()._contains(key)
        file_path = self._bag_file(key)
        if not file_path.is_file():
            return False
        try:
            with h5py.File(file_path, "r") as f:
                return key in f
        except OSError:
            return False

    def _evict(self, key: Digest) -> None:
        if self.prefix_length is None:
            return super()._evict(key)
        file_path = self._bag_file(key)
        lock_path = self._lock_path(key)
        with filelock.FileLock(lock_path, timeout=self.lock_timeout):
            if not file_path.is_file():
                return
            with h5py.File(file_path, "a") as f:
                if key in f:
                    del f[key]
                remaining = len(f)
            if remaining == 0:
                file_path.unlink(missing_ok=True)
                lock_path.unlink(missing_ok=True)

    def list(self) -> Iterable[Digest]:
        if self.prefix_length is None:
            return super().list()
        self.root.mkdir(parents=True, exist_ok=True)
        keys = []
        for p in self.root.iterdir():
            if not p.is_file() or not p.name.endswith(".h5"):
                continue
            try:
                with h5py.File(p, "r") as f:
                    keys.extend(Digest(name) for name in f.keys())
            except OSError as e:
                logger.error("Corrupt file present in cache at path %s: %s", p, e, exc_info=True)
        return keys

    def rebag(self, version_validator: VersionValidator = "none") -> None:
        """Re-open and re-save all bags using the given version validator.

        Useful when bags were created with an older library version and
        would otherwise fail strict version checking on load.
        """
        for key in list(self.list()):
            path = self._path(key)
            with self._operation_context(key):
                try:
                    value = H5Bag(path, _skip_load=True).load(version_validator=version_validator)
                    H5Bag.save(value, path)
                except OSError as e:
                    logger.warning("Failed to rebag %s: %s", key, e)


@dataclass(frozen=True)
class ValueBagOfHoldingH5File(PerKeyLockMixin, DestructuringMixin, ValueMixin, BagOfHoldingH5FileBackend): ...

@dataclass(frozen=True)
class CallBagOfHoldingH5File(PerKeyLockMixin, CallMixin, BagOfHoldingH5FileBackend): ...
