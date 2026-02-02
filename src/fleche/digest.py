import hashlib
import dataclasses
import struct
from collections.abc import Iterable

import numpy as np

from .invocation import Invocation


class Unhashable(Exception):
    pass


def digest(value) -> str:
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
            for k, v in value.items():
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
