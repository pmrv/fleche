import importlib
import pickle
import logging
import gzip
import types
from dataclasses import dataclass, field
from typing import Any

from .file import FileStorage
from ..digest import Digest
from ..security import get_secret_key, SignedBytes, SignatureError

from pyiron_snippets.import_alarm import ImportAlarm

logger = logging.getLogger("fleche.storage.pickle_file")

_HMAC_MIN_KEY_BYTES = 32


def _normalize_secret_key(key) -> list[bytes]:
    """
    Normalize a secret key value to ``list[bytes]``.

    Accepts:
    - ``bytes``: wrapped in a list
    - ``str``: split on ``":"`` delimiter, each part encoded to UTF-8
    - ``list[bytes]``: each element validated for minimum length
    - ``list[str]``: each element (or colon-delimited parts) encoded to UTF-8

    Each resulting key must be at least ``_HMAC_MIN_KEY_BYTES`` bytes long.

    Raises:
        TypeError: if ``key`` or any element is not ``bytes`` or ``str``.
        ValueError: if any resulting key is shorter than ``_HMAC_MIN_KEY_BYTES``.
    """
    if isinstance(key, (bytes, str)):
        key = [key]

    if not isinstance(key, list):
        raise TypeError(
            f"secret_key must be bytes, str, or list, got {type(key).__name__}"
        )

    result = []
    for k in key:
        if isinstance(k, str):
            for part in k.split(":"):
                encoded = part.encode("utf-8")
                if len(encoded) < _HMAC_MIN_KEY_BYTES:
                    raise ValueError(
                        f"Each secret key must be at least {_HMAC_MIN_KEY_BYTES} bytes, "
                        f"got {len(encoded)}"
                    )
                result.append(encoded)
        elif isinstance(k, bytes):
            if len(k) < _HMAC_MIN_KEY_BYTES:
                raise ValueError(
                    f"Each secret key must be at least {_HMAC_MIN_KEY_BYTES} bytes, "
                    f"got {len(k)}"
                )
            result.append(k)
        else:
            raise TypeError(
                f"Each element of secret_key must be bytes or str, "
                f"got {type(k).__name__}"
            )

    return result

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


@dataclass(kw_only=True)
class PickleFile(FileStorage):
    """
    Store values as files on the filesystem using a serialization module.
    """

    secret_key: list[bytes] = field(default_factory=list)
    serializer: Any = field(repr=False)
    compress: bool = False

    def __post_init__(self):
        super().__post_init__()
        if not self.secret_key:
            self.secret_key = get_secret_key()
        else:
            self.secret_key = _normalize_secret_key(self.secret_key)

    @classmethod
    def with_pickle(cls, *args, **kwargs):
        """Construct a PickleFile using the standard pickle module."""
        return cls(*args, serializer=pickle, **kwargs)

    @classmethod
    @cloudpickle_alarm
    def with_cloudpickle(cls, *args, **kwargs):
        """Construct a PickleFile using the cloudpickle module."""
        return cls(*args, serializer=cloudpickle, **kwargs)

    @classmethod
    @dill_alarm
    def with_dill(cls, *args, **kwargs):
        """Construct a PickleFile using the dill module."""
        return cls(*args, serializer=dill, **kwargs)

    def __getstate__(self):
        state = self.__dict__.copy()
        serializer = state.get("serializer")
        if isinstance(serializer, types.ModuleType):
            state["serializer"] = serializer.__name__
        return state

    def __setstate__(self, state):
        serializer_name = state.get("serializer")
        if isinstance(serializer_name, str):
            state = dict(state)
            state["serializer"] = importlib.import_module(serializer_name)
        self.__dict__.update(state)

    def _save(self, value: Any, key: Digest) -> Digest:
        signer = SignedBytes(self.secret_key)
        data = signer.dumps(self.serializer.dumps(value))
        if self.compress:
            data = gzip.compress(data)
        (self._path(key)).write_bytes(data)
        return key

    def _load(self, key: Digest) -> Any:
        try:
            content = (self._path(key)).read_bytes()
            if self.compress:
                content = gzip.decompress(content)
            signer = SignedBytes(self.secret_key)
            data = signer.loads(content)
            return self.serializer.loads(data)
        except FileNotFoundError:
            raise KeyError(key) from None
        except SignatureError:
            raise KeyError(key, "Value present but failed signature check.")
