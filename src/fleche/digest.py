import cmath
import datetime
import hashlib
import logging
import dataclasses
import numbers
from numbers import Number
import struct
import threading
import types
import importlib.metadata
from collections.abc import Iterable, Mapping
from typing import Any, TypeVar, Callable, Type, Generic
import numpy as np
import pandas as pd

from . import _attrs

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
    here to ``m.digest()`` (32 bytes), update ``digest()`` to call ``.hex()``
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
        case Number():
            # Must follow int (int ⊂ Number).
            # lest we have nice things
            if cmath.isnan(value):
                # somehow hash(float('nan')) can yield different values even if having the same sign, because the
                # bespoke python hash special cases nan such that their location in memory is taken into account
                # apparently this is useful:
                # https://github.com/python/cpython/blob/1ac9d138ae0563f2829ba91efe7989af507f47e0/Python/pyhash.c#L59
                # because nans are not singletons this causes the code below to potentially assign different digests to
                # the same nan!  So in this case we revert back to just packing it into binary rep, because negative and
                # positive nans have different binary rep
                if isinstance(value, numbers.Complex):
                    m.update(struct.pack("<dd", value.real, value.imag))
                else:
                    m.update(struct.pack("<d", value))
                # on the other hand the IEEE standard does *not* assign a unique binary representation to NaN, but let's
                # burn that bridge when someone else tries to cross it.
                # the good news is that numpy nans seem to map to the same binary and are also detected by cmath.isnan
            else:
                # rely on python's 'generic' hash semantics for all numbers to translate all of them to an integer
                value = hash(value)
                # then digest its bytes
                return _digest_bytes(value)
        case bytes():
            m.update(value)
        case np.ndarray():
            m.update(_digest_bytes(value.dtype.str))
            m.update(_digest_bytes(value.shape))
            m.update(value.tobytes())
        case np.bool_():
            # np.bool_ ∉ Number so this arm is reachable
            return _digest_bytes(bool(value))
        case pd.DataFrame():
            # DataFrame is Iterable (yields column names) but NOT Mapping, so without
            # this arm two DataFrames sharing column names collide regardless of values.
            #
            # We digest columns/dtypes/index ourselves and pass index=False to
            # hash_pandas_object rather than letting index=True fold the index in.
            # hash_pandas_object only mixes per-element value bytes — it ignores
            # column names, column dtypes, index.name, and index.dtype — so
            # index=True alone would still collide DataFrames whose indices differ
            # only in name or dtype.  Recursing through _digest_bytes on
            # value.index also reuses the pd.Index arm below, keeping a standalone
            # Index and a DataFrame's .index digest-consistent.
            m.update(_digest_bytes(list(value.columns)))
            m.update(_digest_bytes([str(d) for d in value.dtypes]))
            m.update(_digest_bytes(value.index))
            m.update(pd.util.hash_pandas_object(value, index=False).values.tobytes())
        case pd.Series():
            # Same reasoning as DataFrame: hash_pandas_object ignores name/dtype/
            # index metadata, so we digest those ourselves and pass index=False.
            m.update(_digest_bytes(value.name))
            m.update(_digest_bytes(str(value.dtype)))
            m.update(_digest_bytes(value.index))
            m.update(pd.util.hash_pandas_object(value, index=False).values.tobytes())
        case pd.Index():
            m.update(_digest_bytes(value.name))
            m.update(_digest_bytes(str(value.dtype)))
            m.update(pd.util.hash_pandas_object(value).values.tobytes())
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
