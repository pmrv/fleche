"""Digest arms for pandas objects: ``DataFrame``, ``Series``, ``Index`` and ``pd.NA``.

:func:`fleche.digest._digest_bytes` returns :func:`digest_pandas` for any value
:func:`is_pandas` accepts.  The digest function is passed in because
:mod:`fleche.digest` imports this module.

Object columns need care (#1004).  ``pd.util.hash_pandas_object`` hashes a
column of strings by their encoded bytes, and every missing value by one shared
marker.  It mishandles every other object column:

- unhashable elements such as arrays, lists and dicts make it raise ``TypeError``;
- everything else is hashed through ``str()``, so ``1`` collides with ``"1"`` and
  ``object()`` is keyed on its address.

``bytes`` fall in the second group: ``b"a"`` hashes like ``"a"``.

Such columns are digested element by element with our own hash, and pandas is
handed the column of hex digests instead.  No marker records the swap, so as for
a list, a column digests the same as the column of its elements' digests.
"""

import hashlib
from collections.abc import Callable
from typing import Any

import numpy as np
import pandas as pd
# pandas.util resolves this lazily via __getattr__ (pandas >= 3.1), which type
# checkers see as `object`; import it from where it is defined instead.
from pandas.core.util.hashing import hash_pandas_object
from pandas.api.types import infer_dtype

# What ``infer_dtype`` calls the object columns pandas hashes faithfully.
SAFE_OBJECT = frozenset({"string", "empty"})


def needs_element_digests(values) -> bool:
    """Whether pandas cannot be trusted to hash the elements of *values*."""
    dtype = values.dtype
    if isinstance(dtype, pd.CategoricalDtype):
        # A categorical is hashed by the values of its categories, which suffer
        # the same str() fallback when they are objects.
        values = dtype.categories
        dtype = values.dtype
    return dtype == object and infer_dtype(values, skipna=True) not in SAFE_OBJECT


def element_digests(values, digest_bytes: Callable[[Any], bytes]) -> np.ndarray:
    """Return the hex digest of each element of *values*, as an object array.

    Elements it cannot digest raise :exc:`~fleche.digest.Indigestible`, as they
    would anywhere else, rather than falling back to pandas' unstable ``str()``.
    """
    return np.array([digest_bytes(v).decode() for v in values], dtype=object)


def is_pandas(value: Any) -> bool:
    """Whether :func:`digest_pandas` digests *value*."""
    return isinstance(value, (pd.DataFrame, pd.Series, pd.Index)) or value is pd.NA


def digest_pandas(value, digest_bytes: Callable[[Any], bytes]) -> bytes:
    """Return the digest of the pandas *value*, in the format of *digest_bytes*."""
    # Salted with the type name and returned as hex, exactly as _new_hash and
    # _digest_bytes do, so these digests are the ones the arms had in digest.py.
    m = hashlib.sha256(type(value).__name__.encode())
    match value:
        case pd.DataFrame():
            # We digest columns/dtypes/index ourselves and pass index=False to
            # hash_pandas_object rather than letting index=True fold the index in.
            # hash_pandas_object only mixes per-element value bytes — it ignores
            # column names, column dtypes, index.name, and index.dtype — so
            # index=True alone would still collide DataFrames whose indices differ
            # only in name or dtype.  Recursing through digest_bytes on
            # value.index also reuses the pd.Index arm below, keeping a standalone
            # Index and a DataFrame's .index digest-consistent.
            m.update(digest_bytes(list(value.columns)))
            m.update(digest_bytes([str(d) for d in value.dtypes]))
            m.update(digest_bytes(value.index))
            own = [i for i, (_, col) in enumerate(value.items()) if needs_element_digests(col)]
            if own:
                value = value.copy(deep=False)
                for i in own:
                    # isetitem, not value[label] = ...: column labels may repeat.
                    value.isetitem(i, element_digests(value.iloc[:, i], digest_bytes))
            m.update(hash_pandas_object(value, index=False).values.tobytes())
        case pd.Series():
            # Same reasoning as DataFrame: hash_pandas_object ignores name/dtype/
            # index metadata, so we digest those ourselves and pass index=False.
            m.update(digest_bytes(value.name))
            m.update(digest_bytes(str(value.dtype)))
            m.update(digest_bytes(value.index))
            if needs_element_digests(value):
                value = pd.Series(element_digests(value, digest_bytes), dtype=object)
            m.update(hash_pandas_object(value, index=False).values.tobytes())
        case pd.MultiIndex():
            # pandas hashes a MultiIndex level by level, through str() for object
            # levels, and ignores the level names (value.name is None).  Instead
            # each level is digested as an Index of its values, name included,
            # and the tuple of their digests folded.  The values, not
            # value.levels: those may hold entries no row uses.
            m.update(digest_bytes(tuple(value.get_level_values(i) for i in range(value.nlevels))))
        case pd.Index():
            m.update(digest_bytes(value.name))
            m.update(digest_bytes(str(value.dtype)))
            if needs_element_digests(value):
                value = pd.Index(element_digests(value, digest_bytes), dtype=object)
            m.update(hash_pandas_object(value).values.tobytes())
        case _ if value is pd.NA:
            # A singleton like None; it turns up in object columns, which the
            # arms above digest element by element.
            m.update(b"__NA__")
    return m.hexdigest().encode()
