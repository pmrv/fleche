import hashlib
import dataclasses
from numbers import Number
import types
import importlib.metadata
from collections.abc import Iterable
from typing import Any, TypeVar, Callable
import math

import numpy as np


class Unhashable(Exception):
    """Exception raised when an object cannot be digested."""
    pass


class Digest(str):
    pass


DIGEST_LENGTH = 64


T = TypeVar("T")


@dataclasses.dataclass
class Hook:
    type: T
    digest: Callable[[T], str]


_HOOKS = []
_EP_HOOKS = []


def get_hooks():
    return _HOOKS + _EP_HOOKS


def add_hook(hook: Hook | tuple[str, Callable[[T], str]]):
    if isinstance(hook, tuple):
        hook = Hook(*hook)
    _HOOKS.append(hook)


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
                        print(
                            "INFO",
                            f"add_hook for {hook.type} overrides entry point {ep.value}",
                        )
                    else:
                        for h in _EP_HOOKS:
                            if (h.type is not hook.type) and (h.digest is not hook.digest):
                                print(
                                    "INFO",
                                    f"Digest from {source} overrides later entry point {ep.value}!"
                                )
                    continue

                _EP_HOOKS.append(hook)
                seen_types[hook.type] = ep.value
        except Exception as e:
            print("ERROR", f"Failed to load entry point {ep.name}: {e}")


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
        case Number():
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
            sorted_items = sorted(value.items(), key=lambda item: digest(item[0]))
            for k, v in sorted_items:
                m.update(digest(k).encode())
                m.update(digest(v).encode())
        case np.ndarray():
            m.update(value.tobytes())
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
            fields = map(lambda f: (f.name, getattr(value, f.name)), dataclasses.fields(value))
            m.update(digest(dict(fields)).encode())
        case Iterable():
            for v in value:
                m.update(digest(v).encode())
        case _:
            raise Unhashable(value)

    return Digest(m.hexdigest())
