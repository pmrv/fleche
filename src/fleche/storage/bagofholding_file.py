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
    import bagofholding.content


def _patch_bagofholding():
    """Ensure that bagofholding treats Digest as a generic dict
    and not a StrKeyDict as it would normally do because it
    is a subclass of str."""

    def _get_group_content_class_fixed(
        obj: object,
    ) -> type[bagofholding.content.Group[Any, Any]] | None:
        if isinstance(obj, dict) and all(
            type(k) is str and bagofholding.content.is_simple_string(k) for k in obj
        ):
            return bagofholding.content.StrKeyDict

        return bagofholding.content.KNOWN_GROUP_MAP.get(type(obj))

    bagofholding.content.get_group_content_class = _get_group_content_class_fixed  # ty: ignore[invalid-assignment]


_patched_bagofholding = False


@dataclass
class BagOfHoldingH5File(FileStorage):

    @bagofholding_alarm
    def __post_init__(self):
        global _patched_bagofholding
        if not _patched_bagofholding:
            _patch_bagofholding()
            _patched_bagofholding = True
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
