from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .file import FileStorage
from ..digest import Digest

from pyiron_snippets.import_alarm import ImportAlarm


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

    @cloudpickle_alarm
    def __post_init__(self):
        if hasattr(super(), "__post_init__"):
            super().__post_init__()

    def _save(self, value: Any, key: Digest) -> Digest:
        (self._path(key)).write_bytes(dumps(value))
        return key

    def _load(self, key: Digest) -> Any:
        try:
            return loads((self._path(key)).read_bytes())
        except FileNotFoundError:
            raise KeyError(key) from None
