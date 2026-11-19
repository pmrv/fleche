"""fleche digest hooks for pandas: ``DataFrame``, ``Series``, ``Index``,
``pd.Timedelta`` and ``pd.NA``.

Registered through the ``fleche`` entry point group (see :data:`digest_hooks`),
so installing this package is all it takes.  Without it, fleche does not digest
these values.  A ``pd.Timedelta`` digests by its length in nanoseconds, apart
from the ``datetime.timedelta`` it subclasses.

:data:`destructurers`, under the entry point ``destructure``, makes
``DataFrame``, ``Series`` and ``Index`` leaves of a destructuring store:
inlined into their parent like an ``int``.

Builds on :mod:`fleche_numpy`: object columns are digested element by element.

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

from collections.abc import Callable
from typing import Any

import numpy as np
import pandas as pd
from pandas.api.types import infer_dtype

# The defining module of pd.util.hash_pandas_object, the very same function.
# pandas 3.1 reaches pd.util's names through a module __getattr__ annotated
# ``-> object``, which leaves type checkers nothing callable to check.
from pandas.core.util.hashing import hash_pandas_object

from fleche.hashing import running_hash
from fleche.digest import Digest, Indigestible, digest
from fleche_numpy import timedelta64_length

__all__ = ["destructurers", "digest_hooks", "digest_pandas"]

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


def digest_pandas(value, digest_bytes: Callable[[Any], bytes]) -> bytes:
    """Return the digest of the pandas *value*, in the format of *digest_bytes*.

    Raises KeyError for a ``pd.Timedelta`` in a unit without a known length.
    """
    with running_hash(type(value).__name__.encode()) as m:
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
            case pd.Timedelta():
                # Its exact length in nanoseconds, whatever unit it stores; .value
                # would overflow for a second-unit Timedelta beyond int64 ns.
                # KeyError for a unit without a known length, which the hook
                # raises as Indigestible; pandas only stores s, ms, us or ns.
                _, attoseconds = timedelta64_length(value.to_timedelta64())
                m.update(digest_bytes(attoseconds // 10**9))
            case _ if value is pd.NA:
                # A singleton like None; it turns up in object columns, which the
                # arms above digest element by element.
                m.update(b"__NA__")
    return m.result


def _digest_bytes(value: Any) -> bytes:
    return digest(value).encode()


def _pandas_digest(value) -> Digest:
    try:
        return Digest(digest_pandas(value, _digest_bytes).decode())
    except KeyError as err:
        # A pd.Timedelta in a unit without a known length.
        raise Indigestible(value) from err


#: The hooks fleche loads from this package's ``fleche``/``digest`` entry point.
#: ``pd.Index`` covers its subclasses, ``MultiIndex`` and ``RangeIndex`` among them.
digest_hooks = [
    (pd.DataFrame, _pandas_digest),
    (pd.Series, _pandas_digest),
    (pd.Index, _pandas_digest),
    (pd.Timedelta, _pandas_digest),
    (type(pd.NA), _pandas_digest),
]


def _leaf(intern, value):
    """Destructurer for an atomic value: depth 0, inlined like an ``int``."""
    return value, 0


def _pandas_is_big(value, level: int) -> bool:
    # memory_usage without deep: cheap, but object columns count their pointers only.
    if isinstance(value, pd.DataFrame):
        size = value.memory_usage(index=True, deep=False).sum()
    elif isinstance(value, pd.Series):
        size = value.memory_usage(index=True, deep=False)
    else:
        size = value.memory_usage(deep=False)
    return int(size) >= 1 << level


def _is_pandas_container(value: Any) -> bool:
    return isinstance(value, (pd.DataFrame, pd.Series, pd.Index))


#: The destructurers fleche loads from this package's ``fleche``/``destructure`` entry point:
#: DataFrames, Series and Indexes are leaves, inlined into their parent like an ``int``.
destructurers = [(_is_pandas_container, _leaf, _pandas_is_big)]

