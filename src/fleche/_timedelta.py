"""Digest arm for durations: ``datetime.timedelta``, ``pd.Timedelta`` and ``np.timedelta64``.

:func:`fleche.digest._digest_bytes` returns :func:`digest_timedelta` for every
``datetime.timedelta`` (``pd.Timedelta`` is a subclass) and ``np.timedelta64``,
ahead of its ``Number`` arm: numpy registers ``np.timedelta64`` as
``numbers.Integral``, and a duration must not digest as the bare count it
stores.

A duration of fixed length is digested as its exact length in attoseconds, a
Python int, salted ``timedelta``.  The attosecond is numpy's finest unit, so
every fixed-unit ``np.timedelta64`` (``W`` down to ``as``, and multiples such as
``10ms``), every ``datetime.timedelta`` (microseconds) and every
``pd.Timedelta`` (down to nanoseconds) is a whole number of them, and durations
digest equal exactly when they are the same length, whatever their type and
unit: ``datetime.timedelta(seconds=5)``, ``pd.Timedelta("5s")`` and
``np.timedelta64(5000, "ms")`` all digest alike.  numpy's own ``==`` is not the
reference: it compares two units by casting both to the finer one in int64,
which can overflow silently (``np.timedelta64(2**62, "s")`` compares equal to
the wrapped nanosecond count).

Three kinds of ``np.timedelta64`` have no fixed length and each digest under a
salt of their own, apart from every fixed duration (salts are plain names, as
everywhere else in the digest):

- ``Y`` and ``M`` vary in length.  numpy compares them only with each other, a
  year as twelve months, and refuses to compare them with fixed units, so they
  are digested as their exact count of months.
- The generic unit (``np.timedelta64(5)``) is a bare count waiting for a unit;
  numpy calls it equal to ``5`` of any unit, which is not transitive.  It is
  digested as its count.
- NaT, in any unit, equals nothing.  Like a NaN it is one digest for every
  unit.  ``pd.NaT`` is not a timedelta (it subclasses ``datetime.datetime`` and
  stands for missing datetimes too), so it keeps the digest it has.
"""

import numpy as np
import pandas as pd

from ._hashing import running_hash

# Attoseconds in one of each fixed numpy unit.
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
_MONTHS_PER_UNIT = {"Y": 12, "M": 1}
_AS_PER_US = _AS_PER_UNIT["us"]

# Each kind is salted with the name of its canonical type or unit.
_DURATION = b"timedelta"
_CALENDAR = b"timedelta64[M]"
_GENERIC = b"timedelta64"
_NAT_SALT = b"NaT"

_I8 = np.dtype(np.int64)
_NAT = np.iinfo(np.int64).min

# unit -> (salt, multiplier) for np.datetime_data's unit string.  Keyed by the
# unit string rather than the dtype: hashing a dtype costs twice what
# np.datetime_data does.
_SCALES = (
    {unit: (_DURATION, n) for unit, n in _AS_PER_UNIT.items()}
    | {unit: (_CALENDAR, n) for unit, n in _MONTHS_PER_UNIT.items()}
    | {"generic": (_GENERIC, 1)}
)


def _digest_count(salt: bytes, count: int | None) -> bytes:
    with running_hash(salt) as h:
        if count is not None:
            # The int arm's encoding: little-endian two's complement.
            h.update(count.to_bytes((count.bit_length() + 8) // 8, "little", signed=True))
    return h.result


# NaT holds no count, so its digest is the salt alone.
_NAT_DIGEST = _digest_count(_NAT_SALT, None)


def digest_timedelta(value) -> bytes | None:
    """Digest of the duration *value*, or None if its unit is not known.

    A None is for the caller to raise :exc:`~fleche.digest.Indigestible` on.
    """
    if isinstance(value, pd.Timedelta):
        # Its own unit, down to nanoseconds; .value would overflow for a
        # second-unit Timedelta beyond int64 nanoseconds.
        value = value.to_timedelta64()
    if isinstance(value, np.timedelta64):
        count = int(value.view(_I8))
        if count == _NAT:
            return _NAT_DIGEST
        unit, multiple = np.datetime_data(value.dtype)
        scale = _SCALES.get(unit)
        if scale is None:
            return None
        salt, per_unit = scale
        return _digest_count(salt, count * multiple * per_unit)
    # datetime.timedelta normalises to days, seconds (< 86400) and
    # microseconds (< 10**6); its subclasses other than pd.Timedelta are taken
    # as the duration they hold.
    micro = (value.days * 86400 + value.seconds) * 1_000_000 + value.microseconds
    return _digest_count(_DURATION, micro * _AS_PER_US)
