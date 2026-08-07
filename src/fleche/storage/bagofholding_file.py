from dataclasses import dataclass, field, replace, InitVar
from pathlib import Path
from typing import Any, Literal, Iterable
import logging
import filelock

from .file import FileStorage
from .base import SaveError, ValueMixin, CallMixin, register_storage
from .thread_safe import PerKeyLockMixin
from .destructuring import DestructuringMixin
from ..digest import Digest, DIGEST_LENGTH

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

_DEFAULT_PREFIX_LENGTH = 2


def _validate_prefix_length(prefix_length: Any) -> None:
    if not isinstance(prefix_length, int) or not 0 <= prefix_length <= DIGEST_LENGTH:
        raise ValueError(
            f"prefix_length must be an integer between 0 (one file per key) and "
            f"{DIGEST_LENGTH}, got {prefix_length!r}!"
        )


def _observed_prefix_lengths(root: Path) -> set[int]:
    """Prefix lengths of all fleche-written files in *root* (``0`` = per-key).

    Multi-bag files are named ``{prefix}.h5`` and per-key files by the full
    digest, so the prefix length a file was written with can be read off its
    name.  Files this backend never writes (locks, dotfiles, anything else)
    are ignored.
    """
    observed = set()
    if not root.is_dir():
        return observed
    for p in root.iterdir():
        if not p.is_file() or p.name.startswith(".") or p.name.endswith(".lock"):
            continue
        if p.name.endswith(".h5"):
            observed.add(len(p.name) - len(".h5"))
        elif len(p.name) == DIGEST_LENGTH:
            observed.add(0)
    return observed


@dataclass(frozen=True)
class BagOfHoldingH5FileBackend(FileStorage):
    version_validator: VersionValidator | None = None
    # Keys sharing the first `prefix_length` characters are multiplexed as sibling
    # groups (named by the full key) into one file at root/{prefix}.h5, instead of
    # each key getting its own file.  `0` keeps one file per key; `None` infers the
    # length from the files already in root (falling back to the default on an
    # empty root), so it is always an int after construction.
    prefix_length: int | None = _DEFAULT_PREFIX_LENGTH
    # Init-only: skip the check that `prefix_length` matches the files already in
    # root.  Only allowed together with an explicit `prefix_length`; the storage
    # then blindly operates on files of exactly that length, ignoring all others —
    # this is how `refix`/`consolidate` address one layout of a mixed root.
    check_consistency: InitVar[bool] = True

    @bagofholding_alarm
    def __post_init__(self, check_consistency: bool = True):
        if hasattr(super(), "__post_init__"):
            super().__post_init__()
        if self.prefix_length is None:
            if not check_consistency:
                raise ValueError(
                    "check_consistency=False requires an explicit prefix_length!"
                )
            object.__setattr__(self, "prefix_length", self._infer_prefix_length())
        else:
            _validate_prefix_length(self.prefix_length)
            if check_consistency:
                self._check_prefix_consistency()

    def _infer_prefix_length(self) -> int:
        observed = _observed_prefix_lengths(self.root)
        if len(observed) > 1:
            raise ValueError(
                f"Cannot infer prefix_length: files in {self.root} mix prefix "
                f"lengths {sorted(observed)} (0 = one file per key); repair with "
                f"{type(self).__name__}.consolidate()."
            )
        return observed.pop() if observed else _DEFAULT_PREFIX_LENGTH

    def _check_prefix_consistency(self) -> None:
        """Raise :class:`ValueError` if files already in :attr:`~fleche.storage.file.FileStorage.root` were
        written with a different prefix length."""
        others = _observed_prefix_lengths(self.root) - {self.prefix_length}
        if others:
            raise ValueError(
                f"prefix_length={self.prefix_length} does not match existing "
                f"files in {self.root} written with prefix length(s) "
                f"{sorted(others)} (0 = one file per key); open the storage "
                f"with the matching prefix_length and call "
                f"refix({self.prefix_length}) to migrate, or use "
                f"{type(self).__name__}.consolidate() to unify a mixed root."
            )

    def refix(self, prefix_length: int) -> "BagOfHoldingH5FileBackend":
        """Copy every stored entry into a new prefix-length layout.

        Originals are evicted as soon as their entries are copied, so the
        transient extra disk usage stays bounded by a single entry (per-key
        mode) or a single bag file (multi-bag mode — the old bag is unlinked
        by :meth:`_evict` the moment its last entry goes, and HDF5 files do
        not shrink before that anyway).  ``self`` is left untouched: it keeps
        addressing the old — afterwards empty — layout, and the returned
        storage addresses the new one.

        The migration is not atomic, but resumable: entries already present
        in the target layout are skipped, so re-running never re-copies work
        already done, and :meth:`consolidate` repairs a root left with both
        layouts by an interrupted or aborted run (no data is lost either
        way).

        Args:
            prefix_length: target prefix length, between ``0`` (one file per
                key) and :data:`~fleche.digest.DIGEST_LENGTH`.  Must be
                explicit — ``None`` is not accepted.

        Returns:
            BagOfHoldingH5FileBackend: a storage of the same type at the same
                root addressing the new layout; ``self`` when *prefix_length*
                already matches.

        Raises:
            ValueError: if *prefix_length* is not an integer in range.
            RuntimeError: if an entry cannot be read — silently skipping it
                would make the *next* instantiation fail its consistency
                check instead.  Migration aborts immediately, leaving both
                layouts present.
        """
        _validate_prefix_length(prefix_length)
        if prefix_length == self.prefix_length:
            return self
        target = replace(self, prefix_length=prefix_length, check_consistency=False)
        # sorted() forces full collection before the first write, so files the
        # target creates in the same root can never leak into the iteration,
        # and keeps keys sharing a bag contiguous so each old bag is drained —
        # and thereby unlinked by _evict — before the next one is touched.
        for key in sorted(self.list()):
            with self._operation_context(key):
                self._refix_one(target, key)
                self._evict(key)
        return target

    def _refix_one(self, target: "BagOfHoldingH5FileBackend", key: Digest) -> None:
        """Copy one entry into *target*'s layout, skipping entries a previous
        (aborted) migration already moved."""
        if target._contains(key):
            return
        try:
            value = self.get(key)
        except KeyError:
            raise RuntimeError(
                f"Aborting refix: entry {key} could not be read. The storage "
                f"now contains both layouts; remove or restore the unreadable "
                f"entry, then repair with {type(self).__name__}.consolidate()."
            ) from None
        target.put(value, key)

    @classmethod
    def consolidate(
        cls, root: Path | str, prefix_length: int = _DEFAULT_PREFIX_LENGTH, **kwargs
    ) -> "BagOfHoldingH5FileBackend":
        """Open *root* regardless of which prefix lengths it contains, migrate
        everything to *prefix_length*, and return the resulting storage.

        This is the repair constructor for roots holding several layouts at
        once — e.g. after an interrupted :meth:`refix`, or after entries were
        written with different ``prefix_length`` settings.  Every other
        prefix length found in *root* is converted via :meth:`refix`.

        Args:
            root: storage directory to open.
            prefix_length: target prefix length, between ``0`` (one file per
                key) and :data:`~fleche.digest.DIGEST_LENGTH`.
            **kwargs: forwarded to the constructor (e.g. ``lock_timeout``,
                ``version_validator``).

        Returns:
            BagOfHoldingH5FileBackend: a consistency-checked storage at
                *root* with every entry stored under *prefix_length*.
        """
        _validate_prefix_length(prefix_length)
        root = Path(root)
        probe = cls(root, prefix_length=prefix_length, check_consistency=False, **kwargs)
        for length in sorted(_observed_prefix_lengths(probe.root) - {prefix_length}):
            cls(root, prefix_length=length, check_consistency=False, **kwargs).refix(
                prefix_length
            )
        return cls(root, prefix_length=prefix_length, **kwargs)

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
        """Path to hand to :class:`~bagofholding.h5.bag.H5Bag`: the plain per-key file, or the
        composite ``file.h5/{key}`` group path in multi-bag mode."""
        if self.prefix_length == 0:
            return super()._path(key)
        return self._bag_file(key) / key

    def _lock_path(self, key: str) -> Path:
        if self.prefix_length == 0:
            return super()._lock_path(key)
        return Path(f"{self._bag_file(key)}.lock")

    def _contains(self, key: Digest) -> bool:
        if self.prefix_length == 0:
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
        if self.prefix_length == 0:
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
        # Only files of exactly this instance's prefix length are considered,
        # so a storage constructed with check_consistency=False can address one
        # layout of a mixed root without seeing the others' files.
        self.root.mkdir(parents=True, exist_ok=True)
        if self.prefix_length == 0:
            return [
                Digest(p.name)
                for p in self.root.iterdir()
                if p.is_file() and len(p.name) == DIGEST_LENGTH
            ]
        keys = []
        for p in self.root.iterdir():
            if (
                not p.is_file()
                or not p.name.endswith(".h5")
                or len(p.name) - len(".h5") != self.prefix_length
            ):
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


@register_storage("bagofholding_hdf", kind="value")
@dataclass(frozen=True)
class ValueBagOfHoldingH5File(PerKeyLockMixin, DestructuringMixin, ValueMixin, BagOfHoldingH5FileBackend):
    def to_config(self) -> dict[str, Any]:
        return {
            "type": "bagofholding_hdf",
            # `root` is a Path; config dicts must stay TOML/JSON-representable.
            "root": str(self.root),
            "lock_timeout": self.lock_timeout,
            "version_validator": self.version_validator,
            "prefix_length": self.prefix_length,
            "remaining_depth": self.remaining_depth,
        }

@register_storage("bagofholding_hdf", kind="call")
@dataclass(frozen=True)
class CallBagOfHoldingH5File(PerKeyLockMixin, CallMixin, BagOfHoldingH5FileBackend):
    def to_config(self) -> dict[str, Any]:
        return {
            "type": "bagofholding_hdf",
            "root": str(self.root),
            "lock_timeout": self.lock_timeout,
            "version_validator": self.version_validator,
            "prefix_length": self.prefix_length,
        }
