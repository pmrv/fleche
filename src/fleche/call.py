from dataclasses import dataclass, field
from typing import Any
from inspect import signature

import fleche.digest


@dataclass
class Call:
    """
    Represents a function call, capturing its name, arguments, and keyword arguments.

    `module` and `version` can be optionally set to be included in the hash of the call.
    `version` should be a plain integer and monotonically increase.  Each different version will completely change the
    hash of the call, invalidating previously cached results.
    """
    name: str
    args: tuple[Any, ...]
    kwargs: dict[str, Any]
    metadata: dict[str, dict[str, Any]] = field(default_factory=dict)
    module: str | None = None
    version: int | None = None
    code_digest: str | None = None
    result: Any = None

    @classmethod
    def from_call(cls, func, *args, **kwargs):
        sig = signature(func).bind(*args, **kwargs)
        sig.apply_defaults()

        inv = cls(func.__name__, sig.args, sig.kwargs)
        if hasattr(func, "__version__"):
            inv.version = func.__version__
        if hasattr(func, "__module__"):
            inv.module = func.__module__
        if hasattr(func, "__code__"):
            inv.code_digest = fleche.digest.digest(func.__code__)
        return inv

    def to_lookup(self):
        return CallLookup(
                name=self.name,
                args=tuple(fleche.digest.digest(a) for a in self.args),
                kwargs={k: fleche.digest.digest(v) for k, v in self.kwargs.items()},
                module=self.module,
                version=self.version,
                code_digest=self.code_digest,
        )


@dataclass(frozen=True)
class CallLookup:
    """Subset of :class:`.Call` to be used as a lookup key """
    name: str
    args: tuple[str, ...]
    kwargs: dict[str, str]
    module: str | None = None
    version: int | None = None
    code_digest: str | None = None
