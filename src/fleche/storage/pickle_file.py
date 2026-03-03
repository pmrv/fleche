from __future__ import annotations

import pickle
import logging
from dataclasses import dataclass, field
from typing import Any

from .file import FileStorage
from ..digest import Digest
from ..security import get_secret_key, SignedBytes, SignatureError

from pyiron_snippets.import_alarm import ImportAlarm

logger = logging.getLogger("fleche.storage.pickle_file")


@dataclass
class PickleFile(FileStorage):
    """
    Store values as files on the filesystem using the standard pickle module for serialization.
    """

    secret_key: list[bytes] = field(default_factory=list)
    serializer: Any = field(default=pickle, repr=False)

    def __post_init__(self):
        super().__post_init__()
        if not self.secret_key:
            self.secret_key = get_secret_key()

    def _save(self, value: Any, key: Digest) -> Digest:
        signer = SignedBytes(self.secret_key)
        data = signer.dumps(self.serializer.dumps(value))
        (self._path(key)).write_bytes(data)
        return key

    def _load(self, key: Digest) -> Any:
        try:
            content = (self._path(key)).read_bytes()
            signer = SignedBytes(self.secret_key)
            data = signer.loads(content)
            return self.serializer.loads(data)
        except FileNotFoundError:
            raise KeyError(key) from None
        except SignatureError:
            raise KeyError(key, "Value present but failed signature check.")


with ImportAlarm(
    "CloudpickleFile requires 'cloudpickle' to be installed. "
    "Install it with `pip install fleche[cloudpickle]`.",
    raise_exception=True,
) as cloudpickle_alarm:
    import cloudpickle


@dataclass
class CloudpickleFile(PickleFile):
    """
    Store values as files on the filesystem using cloudpickle for serialization.
    """

    @cloudpickle_alarm
    def __post_init__(self):
        if self.serializer is pickle:
            self.serializer = cloudpickle
        super().__post_init__()
