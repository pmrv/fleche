from dataclasses import dataclass
from typing import Any


@dataclass
class Invocation:
    """
    Represents a function invocation, capturing its name, arguments, and keyword arguments.

    `module` and `version` can be optionally set to be included in the hash of the invocation.
    `version` should be a plain integer and monotonically increase.  Each different version will completely change the
    hash of the invocation, invalidating previously cached results.
    """
    name: str
    args: tuple[Any, ...]
    kwargs: dict[str, Any]
    module: str | None = None
    version: int | None = None

    @classmethod
    def from_call(cls, func, *args, **kwargs):
        inv = cls(func.__name__, args, kwargs)
        if hasattr(func, "__version__"):
            inv.version = func.__version__
        if hasattr(func, "__module__"):
            inv.module = func.__module__
        return inv
