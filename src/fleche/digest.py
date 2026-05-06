import cmath
import datetime
import hashlib
import logging
import dataclasses
import numbers
from numbers import Number
import struct
import types
import importlib.metadata
from collections.abc import Iterable, Mapping
from typing import Any, TypeVar, Callable, Type, Generic
import numpy as np

from . import _attrs

logger = logging.getLogger("fleche.digest")


class Unhashable(Exception):
    """Exception raised when an object cannot be digested."""

    pass


class Digest(str):
    def expand(self, cache=None) -> "Digest":
        """Expand a short digest prefix to its full-length digest using the cache.

        Args:
            cache: A cache instance to use. If None, uses the current context's cache.

        Returns:
            The full-length :class:`Digest`.
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
            The shortest unambiguous :class:`Digest` prefix.
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
# cases — which means it executes on every recursive ``_digest`` call for plain
# ints, strs, dicts, lists, etc., where the answer is always False.  After the
# first sighting of each built-in type, a set-membership check skips the
# ``hasattr`` MRO walk entirely.  No semantic change for class-defined
# ``__digest__`` (instance-level dunders are not supported anyway).
_TYPES_WITHOUT_DIGEST: set[type] = set()


def get_hooks():
    return list(reversed(_HOOKS)) + _EP_HOOKS


def add_hook(hook: Hook | tuple[Type[T], Callable[[T], str]]):
    if isinstance(hook, tuple):
        hook = Hook(*hook)  # ty: ignore
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
                        for h in _EP_HOOKS:
                            if (h.type is not hook.type) and (
                                h.digest is not hook.digest
                            ):
                                logger.info(
                                    "Digest from %s overrides later entry point %s!",
                                    source,
                                    ep.value,
                                )
                    continue

                _EP_HOOKS.append(hook)
                seen_types[hook.type] = ep.value
        except Exception as e:
            logger.error("Failed to load entry point %s: %s", ep.name, e)


def _digest_mapping(m, contents: Mapping) -> None:
    sorted_items = sorted(
        ((digest(k), k, v) for k, v in contents.items()), key=lambda item: item[0]
    )
    for k_digest, k, v in sorted_items:
        m.update(k_digest.encode())
        m.update(digest(v).encode())


def digest(value: Any) -> Digest:
    try:
        return _digest(value)
    except Unhashable:
        load_entry_points()
    return _digest(value)


def _digest(value: Any) -> Digest:
    """
    Generates a SHA256 digest for a given Python object.

    This function handles various types including strings, bytes, integers, floats, booleans,
    None, dictionaries, numpy arrays, dataclasses, and iterables.
    If an unhashable type is encountered, an Unhashable exception is raised.

    Args:
        value (Any): The object to be digested.

    Returns:
        str: The SHA256 hexdigest of the object.

    Raises:
        Unhashable: If the provided value cannot be digested.
    """
    m = hashlib.sha256()

    # Fast-path: in the common case both hook lists are empty, so skip the
    # ``get_hooks()`` call which would otherwise allocate a fresh combined list
    # on every recursive ``_digest`` invocation (hot for large iterables).
    if _HOOKS or _EP_HOOKS:
        for h in get_hooks():
            if isinstance(value, h.type):
                return h.digest(value)

    # ``__digest__`` opt-in protocol must win over the built-in ``match`` cases
    # so dict/list subclasses can override their own digest.  Avoid the
    # per-call ``hasattr`` MRO walk for the overwhelming common case (plain
    # built-ins) by caching the negative answer in ``_TYPES_WITHOUT_DIGEST``.
    t = type(value)
    if t not in _TYPES_WITHOUT_DIGEST:
        if hasattr(t, "__digest__"):
            return Digest(value.__digest__())
        _TYPES_WITHOUT_DIGEST.add(t)

    m.update(t.__name__.encode())
    match value:
        case Digest():
            return value
        case str():
            m.update(value.encode())
        case bytes():
            m.update(value)
        case int():
            m.update(
                value.to_bytes(
                    (value.bit_length() + 8) // 8, byteorder="little", signed=True
                )
            )
        case Number():
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
                return digest(value)
        case bool():
            m.update(str(value).encode())
        case None:
            m.update(b"__None__")
        case np.bool_():
            return digest(bool(value))
        case np.integer():
            return digest(int(value))
        case np.floating():
            return digest(float(value))
        case np.ndarray():
            m.update(digest(value.dtype.str).encode())
            m.update(digest(value.shape).encode())
            m.update(value.tobytes())
        case types.FunctionType():
            return digest(value.__code__)
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
            m.update(digest(tuple(props)).encode())
        case datetime.timezone():
            m.update(digest(value.utcoffset(None)).encode())
        case datetime.timedelta():
            m.update(digest(value.total_seconds()).encode())
        case datetime.datetime():  # datetime subclasses date; must precede date case
            m.update(value.isoformat().encode())
        case datetime.date():
            m.update(value.isoformat().encode())
        case datetime.time():
            m.update(value.isoformat().encode())
        case staticmethod():
            m.update(digest(value.__func__).encode())
        case classmethod():
            m.update(digest(value.__func__).encode())
        case property():
            m.update(digest((value.fget, value.fset, value.fdel)).encode())
        case _ if dataclasses.is_dataclass(value):
            # cannot use asdict because it recursively converts values which destroys digests
            # instead (flat-) convert to dictionaries, salt with type name, then fallback to dictionary case.
            fields = map(
                lambda f: (f.name, getattr(value, f.name)), dataclasses.fields(value)
            )
            m.update(digest(dict(fields)).encode())
        case _ if _attrs.is_attrs_instance(value):
            # mirror the dataclass digest format so an attrs class and a dataclass
            # with the same name + field layout hash identically.
            m.update(digest(dict(_attrs.field_items(value))).encode())
        case _ if isinstance(value, types.ModuleType):
            names = getattr(value, "__all__", None)
            if names is None:
                names = dir(value)
            _digest_mapping(m, {name: getattr(value, name) for name in names})
        case Mapping():
            _digest_mapping(m, value)
        case Iterable():
            for v in value:
                m.update(digest(v).encode())
        case _:
            raise Unhashable(value)

    return Digest(m.hexdigest())
