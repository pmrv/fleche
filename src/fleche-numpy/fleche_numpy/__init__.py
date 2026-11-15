"""fleche digest hooks for numpy: arrays, ``np.bool_`` and ``np.timedelta64``.

Registered through the ``fleche`` entry point group (see :data:`digest_hooks`),
so installing this package is all it takes.  Without it fleche refuses these
values as :exc:`~fleche.digest.Indigestible` instead of guessing: an array is
``Iterable`` and numpy registers ``np.timedelta64`` as ``numbers.Integral``, so
fleche's built-in arms would otherwise digest them silently and wrongly.

numpy number scalars (``np.float64``, ``np.int32``, ...) are not handled here:
they are numbers, digested by fleche's own :mod:`fleche._numbers`.

The digest functions take the recursive digest as an argument, ``digest_bytes``,
returning the hex digest as bytes; the hooks pass :func:`fleche.digest.digest`.
:mod:`fleche_pandas` builds on :func:`timedelta64_length`.
"""

from collections.abc import Callable
from typing import Any

import numpy as np

from fleche._hashing import running_hash
from fleche.digest import Digest, Indigestible, digest

__all__ = [
    "digest_hooks",
    "digest_numpy",
    "digest_timedelta64",
    "timedelta64_length",
]


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
    if int(value.view(np.int64)) == _NAT:
        with running_hash(b"timedelta64[NaT]") as m:
            pass
        return m.result
    try:
        salt, n = timedelta64_length(value)
    except KeyError:
        return None
    with running_hash(salt) as m:
        m.update(digest_bytes(n))
    return m.result


def timedelta64_length(value) -> tuple[bytes, int]:
    """``(salt, length)`` of the non-NaT ``np.timedelta64`` *value*.

    The length is in attoseconds for a fixed unit (salt ``timedelta64``), in
    months for ``Y``/``M`` and the bare count for the generic unit.  Raises
    KeyError if the unit is not known.
    """
    unit, multiple = np.datetime_data(value.dtype)
    salt, per_unit = _TIMEDELTA64_SCALES[unit]
    return salt, int(value.view(np.int64)) * multiple * per_unit


def _digest_bytes(value: Any) -> bytes:
    return digest(value).encode()


def _array_digest(value: np.ndarray) -> Digest:
    return Digest(digest_numpy(value, _digest_bytes).decode())


def _bool_digest(value: np.bool_) -> Digest:
    return Digest(digest_numpy(value, _digest_bytes).decode())


def _timedelta64_digest(value: np.timedelta64) -> Digest:
    digested = digest_timedelta64(value, _digest_bytes)
    if digested is None:
        raise Indigestible(value)
    return Digest(digested.decode())


#: The hooks fleche loads from this package's ``fleche``/``digest`` entry point.
digest_hooks = [
    (np.ndarray, _array_digest),
    (np.bool_, _bool_digest),
    (np.timedelta64, _timedelta64_digest),
]
