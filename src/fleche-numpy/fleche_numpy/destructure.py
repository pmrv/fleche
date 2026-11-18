"""fleche destructurer for numpy arrays of ``dtype=object``.

Registered through the ``fleche`` entry point ``destructure`` (see
:data:`destructurers`).  An object array holds arbitrary Python objects, so a
destructuring store takes it apart element by element, like a list.  Other
arrays, and ndarray subclasses, stay whole.
"""

from dataclasses import dataclass
from typing import Any

import numpy as np

from fleche.storage.destructuring import Digested

__all__ = ["DigestedArray", "destructurers"]


def _filled(array: np.ndarray, children) -> np.ndarray:
    """A copy of *array* holding *children*, in C order."""
    # copy() is C-contiguous, so reshape(-1) is a view onto it.  Elements are
    # set one at a time so a list or array child is stored as one object
    # instead of being broadcast.
    out = array.copy()
    flat = out.reshape(-1)
    for i, child in enumerate(children):
        flat[i] = child
    return out


@dataclass
class DigestedArray(Digested):
    """A ``dtype=object`` array whose elements are inline values or :class:`~fleche.digest.Digest` references.

    *items* has the shape and type of the original array.  fleche-numpy digests
    object arrays element by element and a ``Digest`` digests as the value it
    names, so the wrapper digests like the original.
    """

    items: np.ndarray

    def underlying(self):
        return self.items

    def child_items(self) -> list[tuple[None, Any]]:
        return [(None, v) for v in self.items.reshape(-1)]

    def mend(self, storage) -> np.ndarray:
        return _filled(self.items, (self.get(storage, v) for v in self.items.reshape(-1)))

    @classmethod
    def _slots(cls, value: np.ndarray) -> list[tuple[None, Any]]:
        return [(None, v) for v in value.reshape(-1)]

    @classmethod
    def _rebuild_plain(cls, value: np.ndarray, labels: tuple, children: tuple) -> np.ndarray:
        # no element became a Digest, so the array itself is the result
        return value

    @classmethod
    def _rebuild_digest(cls, value: np.ndarray, labels: tuple, children: tuple) -> "DigestedArray":
        return cls(_filled(value, children))


def _is_object_array(value: Any) -> bool:
    # Exact ndarrays only: subclasses change what reshape and element access
    # return (np.matrix stays 2-D, a masked array yields np.ma.masked), so
    # they are stored whole.
    return type(value) is np.ndarray and value.dtype.kind == "O"


#: The destructurers fleche loads from this package's ``fleche``/``destructure`` entry point.
destructurers = [(_is_object_array, DigestedArray.sunder)]
