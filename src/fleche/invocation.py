from dataclasses import dataclass, field
from typing import Any

import fleche.digest


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
    metadata: dict[str, dict[str, Any]] = field(default_factory=dict)
    module: str | None = None
    version: int | None = None
    result: Any = None

    @classmethod
    def from_call(cls, func, *args, **kwargs):
        inv = cls(func.__name__, args, kwargs)
        if hasattr(func, "__version__"):
            inv.version = func.__version__
        if hasattr(func, "__module__"):
            inv.module = func.__module__
        return inv

    def to_lookup(self):
        return InvocationLookup(
                name=self.name,
                args=tuple(fleche.digest.digest(a) for a in self.args),
                kwargs={k: fleche.digest.digest(v) for k, v in self.kwargs.items()},
                module=self.module,
                version=self.version,
        )


@dataclass(frozen=True)
class InvocationLookup:
    """Subset of :class:`.Invocation` to be used as a lookup key """
    name: str
    args: tuple[str, ...]
    kwargs: dict[str, str]
    module: str | None = None
    version: int | None = None
