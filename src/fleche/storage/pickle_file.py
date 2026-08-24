import pickle
import gzip
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .file import FileStorage, _atomic_write
from .base import ValueMixin, CallMixin, register_storage
from .thread_safe import PerKeyLockMixin
from .destructuring import DestructuringMixin
from ..security import get_secret_key, normalize_secret_key, SignedBytes, SignatureError

from pyiron_snippets.import_alarm import ImportAlarm

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


_SERIALIZERS: "dict[str, Callable[[], tuple[Callable, Callable]]]" = {}
"""Registered (dumps, loads) providers, keyed by the name used in ``to_config``/``with_serializer``."""


def register_serializer(name: str, loader: "Callable[[], tuple[Callable, Callable]]") -> None:
    """Register a ``(dumps, loads)`` pair for :meth:`PickleFileBackend.with_serializer`.

    *loader* is a zero-argument callable returning the pair; it runs only when
    *name* is actually selected, so an optional serializer's import (and any
    ``ImportAlarm`` gating it) never fires for callers who never ask for it.
    """
    _SERIALIZERS[name] = loader


def _pickle_loader() -> "tuple[Callable, Callable]":
    return pickle.dumps, pickle.loads


@cloudpickle_alarm
def _cloudpickle_loader() -> "tuple[Callable, Callable]":
    return cloudpickle.dumps, cloudpickle.loads


@dill_alarm
def _dill_loader() -> "tuple[Callable, Callable]":
    return dill.dumps, dill.loads


register_serializer("pickle", _pickle_loader)
register_serializer("cloudpickle", _cloudpickle_loader)
register_serializer("dill", _dill_loader)


@dataclass(frozen=True, kw_only=True)
class PickleFileBackend(FileStorage):
    """
    Store values as files on the filesystem using a serialization module.
    """

    secret_key: tuple[bytes, ...] = field(default_factory=tuple)
    serializer: str = "pickle"
    compress: bool = False
    # Derived from `serializer` in `__post_init__` via the `_SERIALIZERS` registry;
    # `init=False` keeps them off the constructor signature.
    dumps: Callable = field(init=False, repr=False)
    loads: Callable = field(init=False, repr=False)

    def __post_init__(self):
        super().__post_init__()
        raw = get_secret_key() if not self.secret_key else normalize_secret_key(self.secret_key)
        object.__setattr__(self, "secret_key", tuple(raw))
        try:
            loader = _SERIALIZERS[self.serializer]
        except KeyError:
            raise ValueError(
                f"Unknown PickleFile serializer {self.serializer!r}; "
                f"registered serializers: {sorted(_SERIALIZERS)}"
            ) from None
        dumps, loads = loader()
        object.__setattr__(self, "dumps", dumps)
        object.__setattr__(self, "loads", loads)

    @classmethod
    def with_serializer(cls, serializer: str, *args, **kwargs):
        """Construct a PickleFileBackend using a registered serializer by name.

        See :func:`register_serializer` for adding new ones.
        """
        return cls(*args, serializer=serializer, **kwargs)

    @classmethod
    def with_pickle(cls, *args, **kwargs):
        """Construct a PickleFileBackend using the standard pickle module."""
        return cls.with_serializer("pickle", *args, **kwargs)

    @classmethod
    def with_cloudpickle(cls, *args, **kwargs):
        """Construct a PickleFileBackend using the cloudpickle module."""
        return cls.with_serializer("cloudpickle", *args, **kwargs)

    @classmethod
    def with_dill(cls, *args, **kwargs):
        """Construct a PickleFileBackend using the dill module."""
        return cls.with_serializer("dill", *args, **kwargs)

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

    def _rewrite_all(self, transform: Callable[[bytes], bytes | None]) -> None:
        """Read and conditionally rewrite every stored file via *transform*.

        *transform* receives the raw file bytes and returns the new bytes to
        write, or ``None`` to leave the file unchanged.  Each rewrite is an
        atomic rename, so concurrent readers see the old or new encoding,
        never a torn file; both encodings decode to the same value.
        """
        for key in list(self.list()):
            path = self._path(key)
            try:
                content = path.read_bytes()
            except FileNotFoundError:
                continue
            result = transform(content)
            if result is not None:
                _atomic_write(path, lambda tmp, data=result: tmp.write_bytes(data))

    def compress_all(self) -> None:
        """Rewrite all stored files in gzip-compressed form."""
        self._rewrite_all(
            lambda c: None if c[:2] == b"\x1f\x8b" else gzip.compress(c)
        )

    def decompress_all(self) -> None:
        """Rewrite all stored files in uncompressed form."""
        self._rewrite_all(
            lambda c: gzip.decompress(c) if c[:2] == b"\x1f\x8b" else None
        )


@dataclass(frozen=True)
class ValuePickleFile(PerKeyLockMixin, DestructuringMixin, ValueMixin, PickleFileBackend):
    def to_config(self) -> dict[str, Any]:
        config: dict[str, Any] = {
            "type": self.serializer,
            # `root` is a Path; config dicts must stay TOML/JSON-representable.
            "root": str(self.root),
            "compress": self.compress,
            "remaining_depth": self.remaining_depth,
        }
        # Keys are bytes; store them hex-encoded, and omit the key list
        # entirely when unset so the config stays minimal.
        if self.secret_key:
            config["secret_key"] = [k.hex() for k in self.secret_key]
        return config

@dataclass(frozen=True)
class CallPickleFile(PerKeyLockMixin, CallMixin, PickleFileBackend):
    def to_config(self) -> dict[str, Any]:
        config: dict[str, Any] = {
            "type": self.serializer,
            "root": str(self.root),
            "compress": self.compress,
        }
        if self.secret_key:
            config["secret_key"] = [k.hex() for k in self.secret_key]
        return config

# One class per kind, three config names each: the serializer is chosen by the
# `with_*` constructor rather than by a config key, so each `to_config` reads
# it back off the instance.
register_storage("pickle", kind="value", factory=ValuePickleFile.with_pickle)(ValuePickleFile)
register_storage("dill", kind="value", factory=ValuePickleFile.with_dill)(ValuePickleFile)
register_storage("cloudpickle", kind="value", factory=ValuePickleFile.with_cloudpickle)(ValuePickleFile)

register_storage("pickle", kind="call", factory=CallPickleFile.with_pickle)(CallPickleFile)
register_storage("dill", kind="call", factory=CallPickleFile.with_dill)(CallPickleFile)
register_storage("cloudpickle", kind="call", factory=CallPickleFile.with_cloudpickle)(CallPickleFile)
