from dataclasses import dataclass, field
from typing import Any, Iterable
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
    arguments: dict[str, Any]
    metadata: dict[str, dict[str, Any]] = field(default_factory=dict)
    module: str | None = None
    version: int | None = None
    code_digest: str | None = None
    result: Any = None

    @classmethod
    def from_call(cls, func, *args, **kwargs):
        # Normalize arguments using function signature
        bound = signature(func).bind(*args, **kwargs)
        bound.apply_defaults()

        # Preserve declared parameter order via bound.arguments (OrderedDict)
        call = cls(func.__name__, dict(bound.arguments))
        if hasattr(func, "__version__"):
            call.version = func.__version__
        if hasattr(func, "__module__"):
            call.module = func.__module__
        if hasattr(func, "__code__"):
            call.code_digest = fleche.digest.digest(func.__code__)
        return call

    def to_lookup(self):
        # Iterate explicitly in the preserved parameter order; do not sort
        arg_pairs = tuple(
            (k, fleche.digest.digest(v))
            for k, v in self.arguments.items()
        )
        return CallLookup(
            name=self.name,
            arguments=arg_pairs,
            module=self.module,
            version=self.version,
            code_digest=self.code_digest,
        )


@dataclass(frozen=True)
class CallLookup:
    """Subset of :class:`.Call` to be used as a lookup key """
    name: str
    arguments: tuple[tuple[str, str], ...]
    module: str | None = None
    version: int | None = None
    code_digest: str | None = None
