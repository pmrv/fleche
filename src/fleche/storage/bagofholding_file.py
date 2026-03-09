from dataclasses import dataclass
from typing import Any
import logging

from .file import FileStorage
from .base import SaveError
from ..digest import Digest

from pyiron_snippets.import_alarm import ImportAlarm

logger = logging.getLogger("fleche.storage.bagofholding_file")

with ImportAlarm(
    "BagOfHoldingH5File requires 'bagofholding' to be installed. "
    "Install it with `pip install fleche[bagofholding]`.",
    raise_exception=True,
) as bagofholding_alarm:
    from bagofholding import H5Bag


@dataclass
class BagOfHoldingH5File(FileStorage):

    @bagofholding_alarm
    def __post_init__(self):
        if hasattr(super(), "__post_init__"):
            super().__post_init__()

    def _save(self, value: Any, key: Digest) -> Digest:
        try:
            H5Bag.save(value, self._path(key))
        except (ValueError, TypeError):  # h5py choked on something, pass it along
            raise SaveError(value) from None
        return key

    def _load(self, key: str) -> Any:
        try:
            return H5Bag(self._path(key)).load()
        except FileNotFoundError:
            raise KeyError(key) from None
        except OSError as e:
            logger.error(f"Corrupt file present in cache for key {key}: {e}")
            raise KeyError(key) from e
