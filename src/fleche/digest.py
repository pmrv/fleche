import cmath
import datetime
import hashlib
import logging
import math
import dataclasses
from decimal import Decimal
from fractions import Fraction
import numbers
from numbers import Number
import struct
import threading
import types
import importlib.metadata
from collections.abc import Iterable, Mapping
from typing import Any, TypeVar, Callable, Type, Generic
import numpy as np

from . import _attrs, _pandas

logger = logging.getLogger("fleche.digest")


class Indigestible(Exception):
    """Exception raised when an object cannot be digested."""

    pass


class Digest(str):
    def expand(self, cache=None) -> "Digest":
        """Expand a short digest prefix to its full-length digest using the cache.

        Args:
            cache: A cache instance to use. If None, uses the current context's cache.

        Returns:
            The full-length :class:`~fleche.digest.Digest`.
        """
        if cache is None:
            from .state import cache as get_cache
            cache = get_cache()
        return cache.expand(self)

    def shrink(self, cache=None) -> "Digest":
        """Shrink a digest to its shortest unambiguous prefix using the cache.

        Args:
            cache: A cache instance to use. If None, uses the current context's cache.

        Returns:
            The shortest unambiguous :class:`~fleche.digest.Digest` prefix.
        """
        if cache is None:
            from .state import cache as get_cache
            cache = get_cache()
        return cache.shrink(self)


DIGEST_LENGTH = 64


T = TypeVar("T")


@dataclasses.dataclass
class Hook(Generic[T]):
    type: T
    digest: Callable[[T], str | Digest]


_HOOKS = []
_EP_HOOKS = []

# Types confirmed *not* to define ``__digest__``.  ``__digest__`` is the opt-in
# protocol that lets user types (including subclasses of dict/list/...) take
# over their own digest, so the check has to run before the built-in ``match``
# cases — which means it executes on every recursive ``_digest_bytes`` call for
# plain ints, strs, dicts, lists, etc., where the answer is always False.  After
# the first sighting of each built-in type, a set-membership check skips the
# ``hasattr`` MRO walk entirely.  No semantic change for class-defined
# ``__digest__`` (instance-level dunders are not supported anyway).
_TYPES_WITHOUT_DIGEST: set[type] = set()


def get_hooks():
    return list(reversed(_HOOKS)) + _EP_HOOKS


def add_hook(hook: Hook | tuple[Type[T], Callable[[T], str]]):
    if isinstance(hook, tuple):
        hook = Hook(*hook)
        _HOOKS.append(hook)
    elif isinstance(hook, Hook):
        _HOOKS.append(hook)
    else:
        raise ValueError("Must be a Hook instance or (type, digest function) tuple!")


def load_entry_points():
    _EP_HOOKS.clear()
    eps = importlib.metadata.entry_points(group="fleche", name="digest")

    seen_types = {h.type: "add_hook" for h in _HOOKS}

    for ep in eps:
        try:
            hooks = ep.load()
            if not isinstance(hooks, list):
                hooks = [hooks]

            for hook in hooks:
                if isinstance(hook, tuple):
                    hook = Hook(*hook)

                if hook.type in seen_types:
                    source = seen_types[hook.type]
                    if source == "add_hook":
                        logger.info(
                            "add_hook for %s overrides entry point %s",
                            hook.type,
                            ep.value,
                        )
                    else:
                        logger.info(
                            "%s already provides a digest for %s; ignoring entry point %s",
                            source,
                            hook.type,
                            ep.value,
                        )
                    continue

                _EP_HOOKS.append(hook)
                seen_types[hook.type] = ep.value
        except Exception as e:
            logger.error("Failed to load entry point %s: %s", ep.name, e, exc_info=True)


def _new_hash(salt: bytes):
    """Start a running SHA256 under *salt*.

    Every digest in this module is a salted accumulation: the salt discriminates
    what kind of thing is being hashed (a type name, a section of a function's
    captured state) before any content goes in.
    """
    m = hashlib.sha256()
    m.update(salt)
    return m


def digest_class(cls: type) -> Digest:
    """Digest a class by its qualified name, ``module.QualName``.

    This identifies a class *as a class* — a name, not a value.  It is what the
    built-in ``type`` arm hashes and what a method's compiler-inserted
    ``__class__`` cell folds in.  Digesting a class as an ordinary *value* is a
    different question, and still raises :exc:`Indigestible` for anything
    outside ``builtins``.
    """
    return digest(f"{cls.__module__}.{cls.__qualname__}")


def _digest_mapping(m, contents: Mapping) -> bytes:
    sorted_items = sorted(
        ((_digest_bytes(k), k, v) for k, v in contents.items()), key=lambda item: item[0]
    )
    for k_bytes, k, v in sorted_items:
        m.update(k_bytes)
        m.update(_digest_bytes(v))
    return m.hexdigest().encode()


# Salt + section markers + placeholders for the captured-state digest.  Kept as
# module-level constants so the wire format is greppable and cannot drift
# between the two call sites.
_CAPTURED_SALT = b"__fleche_captured__"
_FREEVARS_SECTION = "__closure__"
_DEFAULTS_SECTION = "__defaults__"
_KWDEFAULTS_SECTION = "__kwdefaults__"
_RECEIVER_SECTION = "__self__"
_EMPTY_CELL = "__fleche_empty_cell__"
_RECURSIVE_FUNCTION = "__fleche_recursive_function__"

# Captured state is digested *by value*, so a function that refers to itself —
# the ordinary shape of a recursive inner function, and reachable through a
# default too — or two functions that refer to each other would recurse forever.
# Each function currently being walked is remembered with its depth (per thread,
# since digests are computed concurrently); meeting one again folds in a marker
# naming *how far back up the walk* it sits rather than one constant, because
# the constant collided cycles of the same length that close on different
# functions: `a -> b -> a` and `c -> d -> d` are different call graphs.  The
# distance is relative, so a cycle digests the same wherever the walk meets it.
_walking = threading.local()


def _fold_freevars(m, code, closure) -> None:
    """Fold a function's captured cells into the running hash *m*."""
    # __closure__ is ordered to match co_freevars; pairing them keeps the digest
    # tied to the *names* the values are bound to, not just position.
    for name, cell in zip(code.co_freevars, closure):
        m.update(_digest_bytes(name))
        try:
            contents = cell.cell_contents
        except ValueError:
            # An empty cell — the free variable is not bound yet.  It has no
            # value to digest, but its absence is still part of the closure.
            m.update(_digest_bytes(_EMPTY_CELL))
            continue

        if name == "__class__" and isinstance(contents, type):
            # The compiler inserts a ``__class__`` cell into every method that
            # mentions ``super()`` or ``__class__``.  It is not captured state —
            # it is always the class the method was defined in — and
            # user-defined classes are Indigestible as values, so digesting it
            # would refuse every method that calls super().  Identify the class
            # by name instead, exactly as the built-in ``type`` arm does.
            m.update(digest_class(contents).encode())
        else:
            m.update(_digest_bytes(contents))


def _digest_function_bytes(func) -> bytes:
    """Digest a callable by its code object *and* the values bound alongside it.

    Two functions out of one factory share a code object, so what tells
    ``make(1)`` from ``make(2)`` — or ``lambda x, n=1`` from ``lambda x, n=2`` —
    is only the closure cells and the argument defaults, both fixed at
    definition time.  Functions carrying neither keep the historical wire
    format, ``digest(func) == digest(func.__code__)``.
    """
    # ``__digest__`` is checked per instance here, unlike everywhere else: all
    # functions share one type, so a class-level lookup could never distinguish
    # them.  It is how a closure over something indigestible (or fleche's own
    # wrapper) declares its own identity.
    own = getattr(func, "__digest__", None)
    if own is not None:
        return own().encode()

    # getattr rather than attribute access: the only thing call._code_digest
    # checks for is __code__, and an exotic callable carrying that alone must
    # still digest rather than raise AttributeError.
    code = func.__code__
    closure = getattr(func, "__closure__", None)
    defaults = getattr(func, "__defaults__", None)
    kwdefaults = getattr(func, "__kwdefaults__", None)
    if not closure and not defaults and not kwdefaults:
        return _digest_bytes(code)

    active = getattr(_walking, "functions", None)
    if active is None:
        active = _walking.functions = {}
    ident = id(func)
    if ident in active:
        return _digest_bytes((_RECURSIVE_FUNCTION, len(active) - active[ident]))

    active[ident] = len(active)
    try:
        m = _new_hash(_CAPTURED_SALT)
        m.update(_digest_bytes(code))
        if closure:
            m.update(_digest_bytes(_FREEVARS_SECTION))
            _fold_freevars(m, code, closure)
        if defaults:
            # Digested as the plain tuple it is: which parameters they belong to
            # is already pinned by co_varnames inside the code digest, and
            # pairing them up by hand would need index arithmetic that a
            # hand-set __defaults__ longer than co_argcount could silently skew.
            m.update(_digest_bytes(_DEFAULTS_SECTION))
            m.update(_digest_bytes(defaults))
        if kwdefaults:
            # Keyword-only defaults are already a name -> value mapping, so they
            # go through the ordinary Mapping path (sorted by key digest).
            m.update(_digest_bytes(_KWDEFAULTS_SECTION))
            _digest_mapping(m, kwdefaults)
        return m.hexdigest().encode()
    finally:
        del active[ident]


def _refuse_complex(value):
    if isinstance(value, numbers.Complex) and not isinstance(value, numbers.Real):
        # Only ever has an imaginary part here (see _digest_number).  numpy
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
    m = _new_hash(f"__fleche_{name}__".encode())
    for part in parts:
        m.update(part)
    return m.hexdigest().encode()


def _encode_ratio(t: type):
    def encode(value) -> bytes:
        num, den = value.as_integer_ratio()
        if den == 1:
            # Never a second encoding for an integer.
            return _digest_bytes(num)
        return _salted(t.__name__, _digest_bytes(num), _digest_bytes(den))

    return encode


@dataclasses.dataclass(frozen=True)
class _NumberType:
    """A node in the number downcast tree, see :data:`_NUMBER_TREE`."""

    type: type
    # Value -> this type; raises if this type cannot hold the value exactly.
    convert: Callable[[Any], Any]
    # Digest of a value of exactly this type.
    encode: Callable[[Any], bytes]
    children: tuple["_NumberType", ...] = ()


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
_NUMBER_TREE = _NumberType(
    int,
    _as_int,
    lambda v: _digest_bytes(v),  # late-bound: defined below
    (
        _NumberType(
            float,
            _as_float,
            lambda v: _salted("float", struct.pack("<d", v)),
            (
                _NumberType(
                    complex,
                    _as_complex,
                    lambda v: _salted("complex", struct.pack("<dd", v.real, v.imag)),
                ),
                _NumberType(
                    Fraction,
                    _as_fraction,
                    _encode_ratio(Fraction),
                    (_NumberType(Decimal, _as_decimal, _encode_ratio(Decimal)),),
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


_NUMBER_PATHS = dict(_number_paths(_NUMBER_TREE))


def _digest_number(value) -> bytes:
    """Digest a non-NaN number by walking :data:`_NUMBER_TREE` down to its type.

    Python's own ``hash()`` is not used: it reduces the value modulo a
    platform-dependent prime and remaps ``-1`` to ``-2``, so unequal numbers
    such as ``-1.0`` and ``-2.0``, or ``0.5`` and ``2**60``, collide under it.
    """
    if isinstance(value, numbers.Complex) and not isinstance(value, numbers.Real):
        if value.imag == 0:
            # Its real part may need a node off the complex path, e.g. an
            # np.clongdouble whose real part only a Fraction holds.
            return _digest_bytes(value.real)
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
        return node.encode(v)
    # No exact value to digest; a hook can supply one.  Falling back to hash()
    # would bring back the collisions this function exists to avoid.
    raise Indigestible(value)


def _is_nan(value) -> bool:
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
        raise Indigestible(value) from None


def digest(value: Any) -> Digest:
    # A hook for the offending type may simply not be loaded yet, so pay for one
    # rescan before giving up.
    try:
        return Digest(_digest_bytes(value).decode())
    except Indigestible:
        load_entry_points()
    return Digest(_digest_bytes(value).decode())


def _digest_bytes(value: Any) -> bytes:
    """
    Returns bytes representing the SHA-256 digest of *value*.

    All recursive call sites pass the result directly to ``m.update()``.

    **Wire-format note**: currently returns ``m.hexdigest().encode()`` (64 UTF-8
    hex bytes) so the bytes fed into parent hashes are identical to the previous
    ``digest(v).encode()`` calls — no backwards-incompatible change.  To gain
    the raw-bytes speedup (Issue #440), change **only** the final ``return``
    here and in ``_pandas.digest_pandas`` to ``m.digest()`` (32 bytes), update ``digest()`` to call ``.hex()``
    instead of ``.decode()``, and change the ``encode()`` calls on the
    early-return paths (Digest pass-through, hooks, ``__digest__``) to
    ``bytes.fromhex(...)``.  That must be coordinated with a ``hash_version``
    bump and a ``Cache.redigest`` migration.
    """
    # Fast-path: in the common case both hook lists are empty, so skip the
    # ``get_hooks()`` call which would otherwise allocate a fresh combined list
    # on every recursive ``_digest_bytes`` invocation (hot for large iterables).
    if _HOOKS or _EP_HOOKS:
        for h in get_hooks():
            if isinstance(value, h.type):
                return h.digest(value).encode()

    # ``__digest__`` opt-in protocol must win over the built-in ``match`` cases
    # so dict/list subclasses can override their own digest.  Avoid the
    # per-call ``hasattr`` MRO walk for the overwhelming common case (plain
    # built-ins) by caching the negative answer in ``_TYPES_WITHOUT_DIGEST``.
    t = type(value)
    if t not in _TYPES_WITHOUT_DIGEST:
        if hasattr(t, "__digest__"):
            # For raw-bytes speedup (Issue #440): bytes.fromhex(value.__digest__())
            return value.__digest__().encode()
        _TYPES_WITHOUT_DIGEST.add(t)

    m = _new_hash(t.__name__.encode())
    match value:
        case int():
            # Most-frequent arm; bool ⊂ int so booleans are digested here too
            m.update(
                value.to_bytes(
                    (value.bit_length() + 8) // 8, byteorder="little", signed=True
                )
            )
        case Digest():
            # Must precede str (Digest ⊂ str)
            return value.encode()
        case str():
            m.update(value.encode())
        case None:
            m.update(b"__None__")
        case Decimal() if value.is_nan():
            # Must precede Number, whose cmath.isnan raises on a signalling
            # NaN.  str keeps sign, signalling and payload apart.
            return _salted("Decimal NaN", str(value).encode())
        case Number():
            # Must follow int (int ⊂ Number).
            # lest we have nice things
            if _is_nan(value):
                # somehow hash(float('nan')) can yield different values even if having the same sign, because the
                # bespoke python hash special cases nan such that their location in memory is taken into account
                # apparently this is useful:
                # https://github.com/python/cpython/blob/1ac9d138ae0563f2829ba91efe7989af507f47e0/Python/pyhash.c#L59
                # because nans are not singletons this causes the code below to potentially assign different digests to
                # the same nan!  So in this case we revert back to just packing it into binary rep, because negative and
                # positive nans have different binary rep
                if isinstance(value, numbers.Complex):
                    packed = struct.pack("<dd", value.real, value.imag)
                else:
                    packed = struct.pack("<d", value)
                # on the other hand the IEEE standard does *not* assign a unique binary representation to NaN, but let's
                # burn that bridge when someone else tries to cross it.
                # the good news is that numpy nans seem to map to the same binary and are also detected by cmath.isnan
                # One salt for every type, so a NaN digests by its bits alone and
                # np.float64("nan") meets float("nan").
                return _salted("NaN", packed)
            else:
                return _digest_number(value)
        case bytes():
            m.update(value)
        case np.ndarray():
            m.update(_digest_bytes(value.dtype.str))
            m.update(_digest_bytes(value.shape))
            if value.dtype.names is not None:
                for name in value.dtype.names:
                    m.update(_digest_bytes(name))
                    m.update(_digest_bytes(value[name]))  # recurses into the ndarray arm
            elif value.dtype.hasobject:
                # tobytes() of an object array yields memory addresses, digest
                # all elements by value instead
                for element in value.ravel().tolist():
                    m.update(_digest_bytes(element))
            else:
                m.update(value.tobytes())
        case np.bool_():
            # np.bool_ ∉ Number so this arm is reachable
            return _digest_bytes(bool(value))
        case _ if _pandas.is_pandas(value):
            # Must precede Iterable: a DataFrame iterates over its column names
            # only, so the Iterable arm would collide any two frames sharing them.
            return _pandas.digest_pandas(value, _digest_bytes)
        case types.MethodType():
            # A bound method is its function plus the receiver it is bound to.
            # Leaving __self__ out would collide obj1.method with obj2.method —
            # the same shape of bug as digesting a closure by code alone.  A
            # receiver that cannot be digested is refused, exactly as it would
            # be as an argument; a *class* receiver (a classmethod) is named
            # rather than valued, the way the __class__ cell is.
            m.update(_digest_bytes(_RECEIVER_SECTION))
            receiver = value.__self__
            if isinstance(receiver, type):
                m.update(digest_class(receiver).encode())
            else:
                m.update(_digest_bytes(receiver))
            m.update(_digest_function_bytes(value.__func__))
        case types.FunctionType():
            return _digest_function_bytes(value)
        case types.CodeType():
            # captured properties for behavior stability
            props = [
                value.co_code,
                value.co_consts,
                value.co_names,
                value.co_varnames,
                value.co_freevars,
                value.co_cellvars,
                value.co_argcount,
                value.co_posonlyargcount,
                value.co_kwonlyargcount,
                value.co_flags,
            ]
            if hasattr(value, "co_exceptiontable"):
                props.append(value.co_exceptiontable)
            m.update(_digest_bytes(tuple(props)))
        case datetime.timezone():
            m.update(_digest_bytes(value.utcoffset(None)))
        case datetime.timedelta():
            m.update(_digest_bytes(value.total_seconds()))
        case datetime.datetime():  # datetime subclasses date; must precede date case
            m.update(value.isoformat().encode())
        case datetime.date():
            m.update(value.isoformat().encode())
        case datetime.time():
            m.update(value.isoformat().encode())
        case staticmethod():
            m.update(_digest_bytes(value.__func__))
        case classmethod():
            m.update(_digest_bytes(value.__func__))
        case property():
            m.update(_digest_bytes((value.fget, value.fset, value.fdel)))
        case _ if isinstance(value, type) and value.__module__ == 'builtins':
            # Digest a built-in type (int, str, list, …) by its qualified name.
            # Restricted to the builtins module; user-defined types remain Indigestible.
            # This case must precede the dataclasses check: is_dataclass() returns True
            # for both a class and its instances, but getattr(cls, field) raises
            # AttributeError for required fields that have no class-level default.
            return digest_class(value).encode()
        case _ if dataclasses.is_dataclass(value) and not isinstance(value, type):
            # cannot use asdict because it recursively converts values which destroys digests
            # instead (flat-) convert to dictionaries, salt with type name, then fallback to dictionary case.
            fields = map(
                lambda f: (f.name, getattr(value, f.name)), dataclasses.fields(value)
            )
            m.update(_digest_bytes(dict(fields)))
        case _ if _attrs.is_attrs_instance(value):
            # mirror the dataclass digest format so an attrs class and a dataclass
            # with the same name + field layout hash identically.
            m.update(_digest_bytes(dict(_attrs.field_items(value))))
        case _ if isinstance(value, types.ModuleType):
            names = getattr(value, "__all__", None)
            if names is None:
                names = dir(value)
            _digest_mapping(m, {name: getattr(value, name) for name in names})
        case Mapping():
            _digest_mapping(m, dict(value))
        case Iterable():
            for v in value:
                m.update(_digest_bytes(v))
        case _:
            raise Indigestible(value)

    # To gain the raw-bytes speedup (Issue #440): change to m.digest() here,
    # update digest() to use .hex() instead of .decode(), and change the
    # encode()/bytes.fromhex() calls on the early-return paths above.
    return m.hexdigest().encode()
