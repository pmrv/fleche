from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any
import logging

from .file import FileStorage
from ..digest import Digest
from ..security import get_secret_key, SignedBytes, SignatureError

from pyiron_snippets.import_alarm import ImportAlarm

logger = logging.getLogger("fleche.storage.cloudpickle_file")

with ImportAlarm(
    "CloudpickleFile requires 'cloudpickle' to be installed. "
    "Install it with `pip install fleche[cloudpickle]`.",
    raise_exception=True
) as cloudpickle_alarm:
    from cloudpickle import loads, dumps


@dataclass
class CloudpickleFile(FileStorage):
    """
    Store values as files on the filesystem using cloudpickle for serialization.
    """
    secret_key: list[bytes] = field(default_factory=list)

    def __post_init__(self):
        super().__post_init__()
        if not self.secret_key:
            self.secret_key = get_secret_key()

    @cloudpickle_alarm
    def __post_init__(self):
        if hasattr(super(), "__post_init__"):
            super().__post_init__()

    def _save(self, value: Any, key: Digest) -> Digest:
        signer = SignedBytes(self.secret_key)
        data = signer.dumps(dumps(value))
        (self._path(key)).write_bytes(data)
        return key

    def _load(self, key: Digest) -> Any:
        try:
            content = (self._path(key)).read_bytes()
            signer = SignedBytes(self.secret_key)
            data = signer.loads(content)
            return loads(data)
        except FileNotFoundError:
            raise KeyError(key) from None
        except SignatureError:
            raise KeyError(key, "Value present but failed signature check.")
