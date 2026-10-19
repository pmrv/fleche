"""Internal helpers for digesting pandas object columns (#1004).

``pd.util.hash_pandas_object`` hashes a column of strings by their encoded bytes,
and every missing value by one shared marker.  It mishandles every other object
column:

- unhashable elements such as arrays, lists and dicts make it raise ``TypeError``;
- everything else is hashed through ``str()``, so ``1`` collides with ``"1"`` and
  ``object()`` is keyed on its address.

``bytes`` fall in the second group: ``b"a"`` hashes like ``"a"``.

:mod:`fleche.digest` digests such columns element by element with its own hash
and hands pandas the column of hex digests instead.
"""

from collections.abc import Callable
from typing import Any

import numpy as np
import pandas as pd
from pandas.api.types import infer_dtype

# What ``infer_dtype`` calls the object columns pandas hashes faithfully.
SAFE_OBJECT = frozenset({"string", "empty"})
OWN_HASHED_SECTION = "__fleche_own_hashed__"


def needs_own_hash(values) -> bool:
    """Whether pandas cannot be trusted to hash the elements of *values*."""
    dtype = values.dtype
    if isinstance(dtype, pd.CategoricalDtype):
        # A categorical is hashed by the values of its categories, which suffer
        # the same str() fallback when they are objects.
        values = dtype.categories
        dtype = values.dtype
    return dtype == object and infer_dtype(values, skipna=True) not in SAFE_OBJECT


def own_hashed(values, digest_bytes: Callable[[Any], bytes]) -> np.ndarray:
    """Replace each element of *values* by its hex digest under *digest_bytes*.

    *digest_bytes* is passed in because :mod:`fleche.digest` imports this module.
    Elements it cannot digest raise :exc:`~fleche.digest.Indigestible`, as they
    would anywhere else, rather than falling back to pandas' unstable ``str()``.
    """
    return np.array([digest_bytes(v).decode() for v in values], dtype=object)
