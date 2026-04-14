import cmath
import hashlib
import logging
import dataclasses
import numbers
from numbers import Number
import struct
import types
import importlib.metadata
from collections.abc import Iterable
from typing import Any, TypeVar, Callable, Type, Generic
import numpy as np

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

    for h in get_hooks():
        if isinstance(value, h.type):
            return h.digest(value)

    # workaround for numpy removing bool from namespace
    if hasattr(np, "bool") and isinstance(value, np.bool):
        return digest(bool(value))

    m.update(type(value).__name__.encode())
    match value:
        case Digest():
            return value
        case _ if hasattr(value, "__digest__"):
            return Digest(value.__digest__())
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
        case dict():
            # Sort by digest of keys to ensure merkle tree property and order stability
            sorted_items = sorted(
                ((digest(k), k, v) for k, v in value.items()), key=lambda item: item[0]
            )
            for k_digest, k, v in sorted_items:
                m.update(k_digest.encode())
                m.update(digest(v).encode())
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
        case _ if dataclasses.is_dataclass(value):
            # cannot use asdict because it recursively converts values which destroys digests
            # instead (flat-) convert to dictionaries, salt with type name, then fallback to dictionary case.
            fields = map(
                lambda f: (f.name, getattr(value, f.name)), dataclasses.fields(value)
            )
            m.update(digest(dict(fields)).encode())
        case Iterable():
            for v in value:
                m.update(digest(v).encode())
        case _:
            raise Unhashable(value)

    return Digest(m.hexdigest())
