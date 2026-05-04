from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal
import logging

from .file import FileStorage
from .base import SaveError, ValueMixin, CallMixin
from .thread_safe import PerKeyLockMixin
from .destructuring import DestructuringMixin

from pyiron_snippets.import_alarm import ImportAlarm

logger = logging.getLogger("fleche.storage.bagofholding_file")

with ImportAlarm(
    "BagOfHoldingH5File requires 'bagofholding' to be installed. "
    "Install it with `pip install fleche[bagofholding]`.",
    raise_exception=True,
) as bagofholding_alarm:
    from bagofholding import H5Bag

VersionValidator = Literal["exact", "semantic-minor", "semantic-major", "none"]


@dataclass(frozen=True)
class BagOfHoldingH5FileBackend(FileStorage):
    version_validator: VersionValidator | None = None

    @bagofholding_alarm
    def __post_init__(self):
        if hasattr(super(), "__post_init__"):
            super().__post_init__()

    def _to_file(self, value: Any, path: Path) -> None:
        try:
            H5Bag.save(value, path)
        except (ValueError, TypeError):  # h5py choked on something, pass it along
            raise SaveError(value) from None

    def _from_file(self, path: Path) -> Any:
        try:
            kwargs = {}
            if self.version_validator is not None:
                kwargs["version_validator"] = self.version_validator
            return H5Bag(path).load(**kwargs)
        except FileNotFoundError:
            raise KeyError(path) from None
        except OSError as e:
            logger.error(f"Corrupt file present in cache at path {path}: {e}")
            raise KeyError(path) from e

    def rebag(self, version_validator: VersionValidator = "none") -> None:
        """Re-open and re-save all bags using the given version validator.

        Useful when bags were created with an older library version and
        would otherwise fail strict version checking on load.
        """
        for key in list(self.list()):
            path = self._path(key)
            with self._operation_context(key):
                try:
                    value = H5Bag(path).load(version_validator=version_validator)
                    H5Bag.save(value, path)
                except OSError as e:
                    logger.warning("Failed to rebag %s: %s", key, e)


@dataclass(frozen=True)
class ValueBagOfHoldingH5File(PerKeyLockMixin, DestructuringMixin, ValueMixin, BagOfHoldingH5FileBackend): ...

@dataclass(frozen=True)
class CallBagOfHoldingH5File(PerKeyLockMixin, CallMixin, BagOfHoldingH5FileBackend): ...
