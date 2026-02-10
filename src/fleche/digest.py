import hashlib
import dataclasses
import struct
from collections.abc import Iterable
from typing import Any, TypeVar, Callable

import numpy as np

from .invocation import Invocation


class Unhashable(Exception):
    """Exception raised when an object cannot be digested."""
    pass


class Digest(str):
    pass


T = TypeVar("T")

@dataclasses.dataclass
class Hook:
    type: T
    digest: Callable[[T], str]


_HOOKS = []


def get_hooks():
    return _HOOKS


def add_hook(hook: Hook | tuple[str, Callable[[T], str]]):
    if isinstance(hook, tuple):
        hook = Hook(*hook)
    _HOOKS.append(hook)


def digest(value: Any) -> str:
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
            m.update(value.to_bytes((value.bit_length() + 8) // 8, byteorder='little', signed=True))
        case float():
            m.update(struct.pack("<d", value))
        case bool():
            m.update(str(value).encode())
        case None:
            m.update(b"__None__")
        case dict():
            # Sort by digest of keys to ensure merkle tree property and order stability
            sorted_items = sorted(value.items(), key=lambda item: digest(item[0]))
            for k, v in sorted_items:
                m.update(digest(k).encode())
                m.update(digest(v).encode())
        case np.ndarray():
            m.update(value.data)
        case _ if dataclasses.is_dataclass(value):
            # cannot use asdict because it recursively converts values which destroys digests
            # instead (flat-) convert to dictionaries, salt with type name, then fallback to dictionary case.
            fields = map(lambda f: (f.name, getattr(value, f.name)), dataclasses.fields(value))
            m.update(digest(dict(fields)).encode())
        case Iterable():
            for v in value:
                m.update(digest(v).encode())
        case _:
            raise Unhashable(value)

    return Digest(m.hexdigest())
