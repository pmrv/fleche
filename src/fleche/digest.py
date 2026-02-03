import hashlib
import dataclasses
import struct
from collections.abc import Iterable
from typing import Any

import numpy as np


class Unhashable(Exception):
    """Exception raised when an object cannot be digested."""
    pass


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

    match value:
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
            # Sort items to ensure consistent digest for dictionaries
            for k, v in sorted(value.items()):
                m.update(digest(k).encode())
                m.update(digest(v).encode())
        case np.ndarray():
            m.update(value.data)
        case _ if dataclasses.is_dataclass(value):
            m.update(type(value).__name__.encode())
            m.update(digest(dataclasses.asdict(value)).encode())
        case Iterable():
            m.update(type(value).__name__.encode())
            for v in value:
                m.update(digest(v).encode())
        case _:
            raise Unhashable(value)

    return m.hexdigest()
