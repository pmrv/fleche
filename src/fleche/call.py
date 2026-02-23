from dataclasses import dataclass, field, replace
from typing import Any
from inspect import signature

from . import digest


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
    def from_call(cls, func, *args, partial=False, **kwargs):
        # Normalize arguments using function signature
        sig = signature(func)
        if partial:
            bound = sig.bind_partial(*args, **kwargs)
            # missing arguments are set to None
            arguments = {name: bound.arguments.get(name) for name in sig.parameters}
        else:
            bound = sig.bind(*args, **kwargs)
            bound.apply_defaults()
            arguments = dict(bound.arguments)

        # Preserve declared parameter order via bound.arguments (OrderedDict)
        call = cls(func.__name__, arguments)
        if hasattr(func, "__version__"):
            call.version = func.__version__
        if hasattr(func, "__module__"):
            call.module = func.__module__
        if hasattr(func, "__code__"):
            call.code_digest = digest.digest(func.__code__)
        return call

    def to_lookup_key(self):
        # Iterate explicitly in the preserved parameter order; do not sort
        arg_pairs = tuple(self.arguments.items())
        call = replace(self, arguments=arg_pairs, metadata=None, result=None)
        return digest.digest(call)
