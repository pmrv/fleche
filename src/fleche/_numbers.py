"""Digest arm for numbers: ``float``, ``complex``, ``Fraction``, ``Decimal`` and numpy scalars.

:func:`fleche.digest._digest_bytes` returns :func:`digest_number` for every
``numbers.Number`` its ``int`` arm (which also takes ``bool`` and every other
``int`` subclass) has not already claimed.  The digest function is passed in
because :mod:`fleche.digest` imports this module.

A number is digested by walking :data:`NUMBER_TREE` from its root down to the
number's own type and taking the first type on that path that holds the value
exactly.  Non-NaN numbers therefore digest equal exactly when they hold the
same exact value, whatever their types: ``1 == 1.0 == 1+0j == Fraction(1)`` all
digest as ``1``.  Python's own ``hash()`` is not used: it reduces the value
modulo a platform-dependent prime and remaps ``-1`` to ``-2``, so unequal
numbers such as ``-1.0`` and ``-2.0``, or ``0.5`` and ``2**60``, collide under
it.

The reference is the exact value, not ``==`` as numpy computes it: numpy casts
a Python float down to ``float32`` before comparing (NEP 50) and rounds a
``Fraction`` to double.  Converters therefore decide exactness themselves
rather than trusting a trailing ``==``.
"""

import cmath
import dataclasses
import math
import numbers
import struct
from collections.abc import Callable
from decimal import Decimal
from fractions import Fraction
from typing import Any

from ._hashing import running_hash

DigestBytes = Callable[[Any], bytes]


def _refuse_complex(value):
    if isinstance(value, numbers.Complex) and not isinstance(value, numbers.Real):
        # Only ever has an imaginary part here (see digest_number).  numpy
        # would drop it with a warning rather than refuse.
        raise ValueError(value)


def _as_int(value) -> int:
    """Convert to int, refusing anything int cannot hold exactly.

    Decided on the exact ratio rather than by comparing int(value) with value:
    numpy compares a huge np.longdouble with an int through str, which
    sys.int_max_str_digits limits, and taking a Decimal with a large exponent
    to int and back is quadratic.
    """
    if isinstance(value, numbers.Integral):
        return int(value)
    _refuse_complex(value)
    if isinstance(value, numbers.Rational):
        num, den = value.numerator, value.denominator
    elif hasattr(value, "as_integer_ratio"):
        num, den = value.as_integer_ratio()
    else:
        # A foreign Real, which promises __trunc__ but not __int__.
        v = math.trunc(value)
        if v != value:
            raise ValueError(value)
        return int(v)
    if den != 1:
        raise ValueError(value)
    return int(num)


def _as_float(value) -> float:
    _refuse_complex(value)
    v = float(value)
    if v != value:
        raise ValueError(value)
    return v


def _as_complex(value) -> complex:
    v = complex(value)
    if v != value:
        raise ValueError(value)
    return v


def _as_fraction(value) -> Fraction:
    # Exact by construction.  No trailing == check: numpy compares a Fraction
    # against np.longdouble by rounding the Fraction to double first.
    if isinstance(value, numbers.Rational):
        return Fraction(value.numerator, value.denominator)
    if not hasattr(value, "as_integer_ratio"):
        # numbers.Real does not promise one.
        raise TypeError(value)
    return Fraction(*value.as_integer_ratio())


def _as_decimal(value) -> Decimal:
    v = Decimal(value)
    if v != value:
        raise ValueError(value)
    return v


def _salted(name: str, *parts: bytes) -> bytes:
    """Digest *parts* under a salt reserved for the number type *name*.

    Not the bare type name the generic arms salt with, or a user type that
    happens to share the name (a NamedTuple called Fraction) and to feed the
    same bytes would collide with the number.
    """
    with running_hash(f"__fleche_{name}__".encode()) as h:
        for part in parts:
            h.update(part)
    return h.result


def _encode_int(value: int, digest_bytes: DigestBytes) -> bytes:
    # The plain int arm, so an integral value digests exactly as its int.
    return digest_bytes(value)


def _encode_float(value: float, digest_bytes: DigestBytes) -> bytes:
    return _salted("float", struct.pack("<d", value))


def _encode_complex(value: complex, digest_bytes: DigestBytes) -> bytes:
    return _salted("complex", struct.pack("<dd", value.real, value.imag))


def _encode_ratio(t: type):
    def encode(value, digest_bytes: DigestBytes) -> bytes:
        num, den = value.as_integer_ratio()
        if den == 1:
            # Never a second encoding for an integer.
            return digest_bytes(num)
        return _salted(t.__name__, digest_bytes(num), digest_bytes(den))

    return encode


@dataclasses.dataclass(frozen=True)
class NumberType:
    """A node in the number downcast tree, see :data:`NUMBER_TREE`."""

    type: type
    # Value -> this type; raises if this type cannot hold the value exactly.
    convert: Callable[[Any], Any]
    # Digest of a value of exactly this type.
    encode: Callable[[Any, DigestBytes], bytes]
    children: tuple["NumberType", ...] = ()


# The downcast hierarchy for numbers.  A number is digested as the first type
# on the path from the root down to its own type that holds it exactly.  Equal
# numbers therefore digest equal as long as that type lies on both their paths;
# equal numbers on different branches below it would digest apart.  Every
# finite Decimal is an exact Fraction, so the Decimal node only anchors the
# path.  Mirrored in docs/digests/digest_equivalence.rst (a test keeps the two
# in sync):
#
#   int
#   └── float
#       ├── complex
#       └── Fraction
#           └── Decimal
NUMBER_TREE = NumberType(
    int,
    _as_int,
    _encode_int,
    (
        NumberType(
            float,
            _as_float,
            _encode_float,
            (
                NumberType(complex, _as_complex, _encode_complex),
                NumberType(
                    Fraction,
                    _as_fraction,
                    _encode_ratio(Fraction),
                    (NumberType(Decimal, _as_decimal, _encode_ratio(Decimal)),),
                ),
            ),
        ),
    ),
)

# Number types outside the tree hang off it by their numbers ABC, most specific
# first: np.integer under int, np.float32 and np.longdouble under Fraction (so
# float still catches what it can hold), np.complex64 under complex.
_NUMBER_ABCS = (
    (numbers.Integral, int),
    (numbers.Real, Fraction),
    (numbers.Complex, complex),
)


def _number_paths(node, path=()):
    path = path + (node,)
    yield node.type, path
    for child in node.children:
        yield from _number_paths(child, path)


_NUMBER_PATHS = dict(_number_paths(NUMBER_TREE))


def _is_nan(value) -> bool | None:
    """Whether *value* is NaN, or None if it cannot even be asked."""
    if isinstance(value, numbers.Rational):
        # Never NaN, and cmath.isnan would convert it to float, which
        # overflows beyond float's range.
        return False
    try:
        return cmath.isnan(value)
    except OverflowError:
        # Beyond float's range, so not NaN.
        return False
    except TypeError:
        # Neither float() nor complex() takes it.
        return None


def digest_number(value, digest_bytes: DigestBytes) -> bytes | None:
    """Digest of the number *value*, or None if it has no exact value to digest.

    A None is for the caller to raise :exc:`~fleche.digest.Indigestible` on (a
    hook can supply a digest); falling back to ``hash()`` would bring back the
    collisions this module exists to avoid.
    """
    if isinstance(value, Decimal) and value.is_nan():
        # Ahead of the NaN check, whose cmath.isnan raises on a signalling NaN.
        # str keeps sign, signalling and payload apart.
        return _salted("Decimal NaN", str(value).encode())
    nan = _is_nan(value)
    if nan is None:
        return None
    if nan:
        # hash(float('nan')) can differ between NaNs of the same sign: CPython
        # takes a NaN's address into account
        # (https://github.com/python/cpython/blob/1ac9d138ae0563f2829ba91efe7989af507f47e0/Python/pyhash.c#L59),
        # and NaNs are not singletons.  So a NaN is digested by its binary
        # representation instead, which also keeps negative and positive NaNs
        # apart.  IEEE does not assign NaN a unique representation, but let's
        # burn that bridge when someone else tries to cross it; numpy NaNs map
        # to the same binary and are detected by cmath.isnan too.  One salt for
        # every type, so np.float64("nan") meets float("nan").
        if isinstance(value, numbers.Complex):
            packed = struct.pack("<dd", value.real, value.imag)
        else:
            packed = struct.pack("<d", value)
        return _salted("NaN", packed)
    if isinstance(value, numbers.Complex) and not isinstance(value, numbers.Real):
        if value.imag == 0:
            # Its real part may need a node off the complex path, e.g. an
            # np.clongdouble whose real part only a Fraction holds.
            return digest_bytes(value.real)
    path = next(
        (_NUMBER_PATHS[c] for c in type(value).__mro__ if c in _NUMBER_PATHS), None
    )
    if path is None:
        path = next(
            (_NUMBER_PATHS[t] for abc, t in _NUMBER_ABCS if isinstance(value, abc)),
            None,
        )
    for node in path or ():
        try:
            v = node.convert(value)
        except (TypeError, ValueError, ArithmeticError):
            continue
        return node.encode(v, digest_bytes)
    return None
