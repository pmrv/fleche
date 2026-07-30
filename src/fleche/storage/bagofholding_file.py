import contextlib
import os
import threading
import weakref
from collections import OrderedDict
from dataclasses import dataclass, field, replace, InitVar
from pathlib import Path
from typing import Any, Literal, Iterable
import logging
import filelock

from .file import FileStorage
from .base import SaveError, ValueMixin, CallMixin
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


# Cap on read-only bag-file handles kept open between operations.  Handles are
# shared process-wide (keyed by absolute path), so this also bounds the
# process's open-fd contribution regardless of how many storages exist.
_MAX_OPEN_BAGS = 8


def _open_readonly(path: Path) -> "h5py.File":
    """Open *path* read-only without OS-level HDF5 file locking.

    Cached handles stay open between operations; with default locking each
    would hold a shared HDF5 lock that makes every write from *another
    process* fail for as long as the handle lives.  Writes are coordinated by
    ``filelock`` sidecar locks instead, and files rewritten behind our back
    are caught by the stat signature in :class:`_BagHandleCache`.
    """
    try:
        return h5py.File(path, "r", locking=False)
    except (TypeError, ValueError):
        # h5py < 3.5 (no ``locking`` kwarg) or HDF5 < 1.12.1 (no support):
        # fall back to default locking — correct, just briefly blocks writers.
        return h5py.File(path, "r")


class _BagHandleCache:
    """Process-wide cache of open read-only h5py handles for multi-bag files.

    ``_files`` is a weak-value index of the open handles; ``_recent`` keeps
    strong references to the :data:`_MAX_OPEN_BAGS` most recently used ones so
    they survive between operations (a weak-only entry would be collected —
    and the file closed — the moment the operation using it returns).  A
    handle evicted from ``_recent`` is *not* closed eagerly: an operation in
    another thread may still be reading from it, so only the strong reference
    is dropped and the interpreter closes the file once the last user lets go.

    The cache is keyed by absolute path and shared by all storage instances
    rather than kept per-instance: HDF5 refuses to open a file for writing
    while *any* read handle on it is open in the same process (independent of
    OS-level file locking), so a handle cached by one instance must be
    closable by every other instance addressing the same file.

    Every access — read or write — to a bag file must happen while holding
    that file's :meth:`lock`.  Readers hold it for the duration of their use
    of the handle, writers across invalidate-open-write-close, so a writer
    can never close the cached handle under a reader mid-use, and no cached
    handle can be alive during a same-process write open.  Staleness from
    *other* processes is caught by re-validating a ``(inode, mtime, size)``
    stat signature on every acquisition.
    """

    def __init__(self) -> None:
        self._pid = os.getpid()
        self._meta_lock = threading.Lock()
        # Per-bag locks self-prune like PerKeyLockMixin's: alive while any
        # thread holds one (or is inside the with block), recreated otherwise.
        self._bag_locks: weakref.WeakValueDictionary[str, threading.RLock] = (
            weakref.WeakValueDictionary()
        )
        self._files: weakref.WeakValueDictionary[str, "h5py.File"] = (
            weakref.WeakValueDictionary()
        )
        self._recent: OrderedDict[str, "h5py.File"] = OrderedDict()
        self._signatures: dict[str, tuple[int, int, int]] = {}

    def lock(self, path: Path) -> threading.RLock:
        """The in-process lock guarding all access to the bag file at *path*."""
        with self._meta_lock:
            if self._pid != os.getpid():
                # Forked child: inherited handles belong to the parent — drop
                # every reference without closing eagerly (they are read-only,
                # so the close-on-collect in the child is harmless).
                self._pid = os.getpid()
                self._bag_locks = weakref.WeakValueDictionary()
                self._files = weakref.WeakValueDictionary()
                self._recent = OrderedDict()
                self._signatures = {}
            # Hold a strong reference so the lock is not collected between
            # creation and return — WeakValueDictionary only stores a weak ref.
            key = str(path)
            lock = self._bag_locks.get(key)
            if lock is None:
                lock = threading.RLock()
                self._bag_locks[key] = lock
            return lock

    def acquire(self, path: Path) -> "h5py.File | None":
        """A validated open read-only handle for *path*, or ``None`` when the
        file does not exist.  The caller must hold :meth:`lock` for *path*.

        Raises:
            OSError: if the file exists but cannot be opened.
        """
        key = str(path)
        try:
            st = os.stat(key)
        except OSError:
            self.invalidate(path)
            return None
        signature = (st.st_ino, st.st_mtime_ns, st.st_size)
        with self._meta_lock:
            f = self._files.get(key)
            # `not f` is h5py validity: a handle closed behind our back would
            # silently answer False to `key in f` rather than raise.
            if f is not None and (self._signatures.get(key) != signature or not f):
                # Rewritten by another process (or storage instance): safe to
                # close because we hold the bag lock, so no reader is mid-use.
                f.close()
                f = None
        if f is None:
            f = _open_readonly(path)
        # Dropping _meta_lock around the open is race-free because the caller
        # holds the bag lock: no other thread can acquire or invalidate *this*
        # path meanwhile, and activity on other paths never touches this
        # path's entries (MRU eviction only drops their strong references).
        with self._meta_lock:
            self._files[key] = f
            self._signatures[key] = signature
            self._recent[key] = f
            self._recent.move_to_end(key)
            while len(self._recent) > _MAX_OPEN_BAGS:
                self._recent.popitem(last=False)
        return f

    def invalidate(self, path: Path) -> None:
        """Close and drop any cached handle for *path*.  The caller must hold
        :meth:`lock` for *path*."""
        key = str(path)
        with self._meta_lock:
            f = self._files.pop(key, None)
            self._recent.pop(key, None)
            self._signatures.pop(key, None)
        if f is not None:
            f.close()


_bag_handles = _BagHandleCache()


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
        """Raise :class:`ValueError` if files already in :attr:`root` were
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

    def _read_bag(self, file_path: Path, reader):
        """Run *reader* on a cached read-only handle for *file_path*, holding
        the in-process bag lock throughout so no writer can close the handle
        mid-use.  Returns ``None`` when the file does not exist.

        A cached handle that errors mid-read — e.g. broken by an external
        rewrite the stat signature missed — is dropped and the read repeated
        once from a fresh open; only if that fails too does the error
        propagate (the file really is unreadable)."""
        with _bag_handles.lock(file_path):
            for retry in (False, True):
                f = _bag_handles.acquire(file_path)
                if f is None:
                    return None
                try:
                    return reader(f)
                except (OSError, ValueError):
                    # ValueError is h5py's "invalid identifier" from a handle
                    # invalidated behind our back; OSError is a torn/corrupt read.
                    _bag_handles.invalidate(file_path)
                    if retry:
                        raise

    @contextlib.contextmanager
    def _bag_writer(self, key: str):
        """Hold *key*'s in-process bag lock across an operation that opens the
        bag file itself, closing any cached read handle first.  HDF5 refuses a
        same-process write open while any read handle is open, and refuses
        *any* same-process open whose locking flags differ from an existing
        handle's — so this guards not only writes but also :class:`H5Bag`
        reads, which use the default flags rather than the cache's
        ``locking=False``.  No-op in per-key mode, where nothing is cached."""
        if self.prefix_length == 0:
            yield
            return
        file_path = self._bag_file(key)
        with _bag_handles.lock(file_path):
            _bag_handles.invalidate(file_path)
            yield

    def _to_file(self, value: Any, path: Path) -> None:
        # In multi-bag mode `path` is the composite `{prefix}.h5/{key}`, so
        # the key is its final component (in per-key mode _bag_writer ignores it).
        with self._bag_writer(path.name):
            try:
                H5Bag.save(value, path)
            except (ValueError, TypeError):  # h5py choked on something, pass it along
                raise SaveError(value) from None

    def _from_file(self, path: Path) -> Any:
        # H5Bag opens the file itself, so any cached read handle must be
        # closed first and the bag lock held across the load — otherwise the
        # flag-mismatched open would fail (and read as a corrupt file).
        with self._bag_writer(path.name):
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
        try:
            return bool(self._read_bag(self._bag_file(key), lambda f: key in f))
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
            # The unlink stays inside _bag_writer so a reader in another
            # thread cannot re-open (and re-cache) the file between the
            # write-close and its removal.
            with self._bag_writer(key):
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
                bag_keys = self._read_bag(p, lambda f: [Digest(name) for name in f.keys()])
                keys.extend(bag_keys or ())
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
                    # both the load and the save open the file with H5Bag's
                    # own (default) locking flags — see _bag_writer
                    with self._bag_writer(key):
                        value = H5Bag(path, _skip_load=True).load(version_validator=version_validator)
                        H5Bag.save(value, path)
                except OSError as e:
                    logger.warning("Failed to rebag %s: %s", key, e)


@dataclass(frozen=True)
class ValueBagOfHoldingH5File(PerKeyLockMixin, DestructuringMixin, ValueMixin, BagOfHoldingH5FileBackend): ...

@dataclass(frozen=True)
class CallBagOfHoldingH5File(PerKeyLockMixin, CallMixin, BagOfHoldingH5FileBackend): ...
