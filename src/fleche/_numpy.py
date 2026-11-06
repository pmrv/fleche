"""Digest arm for numpy arrays and ``np.bool_``.

:func:`fleche.digest._digest_bytes` returns :func:`digest_numpy` for any value
:func:`is_numpy` accepts.  The digest function is passed in because
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
