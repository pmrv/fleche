"""Digest arms for numpy arrays, ``np.bool_`` and ``np.timedelta64``.

:func:`fleche.digest._digest_bytes` returns :func:`digest_numpy` for any value
:func:`is_numpy` accepts, and :func:`digest_timedelta64` for a timedelta64
ahead of its ``Number`` arm (numpy registers ``np.timedelta64`` as
``numbers.Integral``, but a duration must not digest as its bare count).  The digest function is passed in because
:mod:`fleche.digest` imports this module.  numpy number scalars are not handled
here: they are numbers, digested by :mod:`fleche._numbers`.
"""

from collections.abc import Callable
from typing import Any

import numpy as np

from ._hashing import running_hash


def is_numpy(value: Any) -> bool:
    """Whether :func:`digest_numpy` digests *value*."""
    return isinstance(value, (np.ndarray, np.bool_))


def is_timedelta64(value: Any) -> bool:
    return isinstance(value, np.timedelta64)


def digest_numpy(value, digest_bytes: Callable[[Any], bytes]) -> bytes:
    """Return the digest of the numpy *value*, in the format of *digest_bytes*."""
    if isinstance(value, np.bool_):
        # Not a numbers.Number since numpy 1.20; digests as the builtin bool.
        return digest_bytes(bool(value))
    with running_hash(type(value).__name__.encode()) as m:
        m.update(digest_bytes(value.dtype.str))
        m.update(digest_bytes(value.shape))
        if value.dtype.names is not None:
            for name in value.dtype.names:
                m.update(digest_bytes(name))
                m.update(digest_bytes(value[name]))  # recurses into this arm
        elif value.dtype.hasobject:
            # tobytes() of an object array yields memory addresses, digest
            # all elements by value instead
            for element in value.ravel().tolist():
                m.update(digest_bytes(element))
        else:
            m.update(value.tobytes())
    return m.result


# Attoseconds in one of each fixed numpy timedelta unit; the attosecond is
# numpy's finest, so every fixed unit is a whole number of them.
_AS_PER_UNIT = {
    "W": 7 * 24 * 3600 * 10**18,
    "D": 24 * 3600 * 10**18,
    "h": 3600 * 10**18,
    "m": 60 * 10**18,
    "s": 10**18,
    "ms": 10**15,
    "us": 10**12,
    "ns": 10**9,
    "ps": 10**6,
    "fs": 10**3,
    "as": 1,
}
# unit -> (salt, length of one unit).  Y and M vary in length and numpy only
# compares them with each other, a year as twelve months, so they count months;
# the generic unit is a count still waiting for a unit, which numpy calls equal
# to that count of *every* unit, so it is digested as the bare count.
_TIMEDELTA64_SCALES = (
    {unit: (b"timedelta64", n) for unit, n in _AS_PER_UNIT.items()}
    | {"Y": (b"timedelta64[M]", 12), "M": (b"timedelta64[M]", 1)}
    | {"generic": (b"timedelta64[generic]", 1)}
)
_NAT = np.iinfo(np.int64).min


def digest_timedelta64(value, digest_bytes: Callable[[Any], bytes]) -> bytes | None:
    """Digest of the ``np.timedelta64`` *value* by its exact length, or None if
    its unit is not known.

    Equal lengths digest equal whatever the unit (``5 s``, ``5000 ms`` and
    ``500 * 10ms``); numpy's own ``==`` is not the reference, since it compares
    two units in int64 after casting both to the finer one, which can wrap.
    NaT, which equals nothing, is one digest in every unit.
    """
    count = int(value.view(np.int64))
    if count == _NAT:
        with running_hash(b"timedelta64[NaT]") as m:
            pass
        return m.result
    unit, multiple = np.datetime_data(value.dtype)
    scale = _TIMEDELTA64_SCALES.get(unit)
    if scale is None:
        return None
    salt, per_unit = scale
    with running_hash(salt) as m:
        m.update(digest_bytes(count * multiple * per_unit))
    return m.result
