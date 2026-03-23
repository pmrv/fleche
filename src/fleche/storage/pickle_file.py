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
