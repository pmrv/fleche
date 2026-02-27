from dataclasses import dataclass, field, replace
from typing import Any
from inspect import signature
from collections.abc import Mapping

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


class LazyArguments(Mapping):
    def __init__(self, cache, arg_digests):
        self._cache = cache
        self._arg_digests = arg_digests

    def __getitem__(self, key):
        return self._cache._handle_args_load(self._arg_digests[key])

    def __iter__(self):
        return iter(self._arg_digests)

    def __len__(self):
        return len(self._arg_digests)

    def __repr__(self):
        return f"LazyArguments({self._arg_digests!r})"

    def __digest__(self):
        # Ensuring that LazyArguments digests identically to a dict of the same values.
        # Since self._arg_digests are already Digests, and digest(Digest(X)) == X,
        # this will match a dict of raw values because digest(val) == X.
        return digest.digest(self._arg_digests)


@dataclass(frozen=True)
class LazyCall:
    name: str
    _arguments: dict[str, Any]
    _result: Any
    _cache: Any = field(repr=False, compare=False)
    metadata: dict[str, dict[str, Any]] = field(default_factory=dict)
    module: str | None = None
    version: int | None = None
    code_digest: str | None = None

    @property
    def arguments(self):
        return LazyArguments(self._cache, self._arguments)

    @property
    def result(self):
        return self._cache.load_value(self._result)

    def to_lookup_key(self) -> str:
        # Reconstruct a Call object to ensure identical key calculation
        c = Call(
            name=self.name,
            arguments=self._arguments,
            metadata=self.metadata,
            module=self.module,
            version=self.version,
            code_digest=self.code_digest,
            result=None
        )
        return c.to_lookup_key()

    def to_call(self) -> Call:
        """Reconstruct a full Call object by loading all values from the cache."""
        return Call(
            name=self.name,
            arguments=dict(self.arguments),
            metadata=self.metadata,
            module=self.module,
            version=self.version,
            code_digest=self.code_digest,
            result=self.result
        )

    def __digest__(self):
        # Reconstruct a Call object to ensure identical digest calculation
        c = Call(
            name=self.name,
            arguments=self._arguments,
            metadata=self.metadata,
            module=self.module,
            version=self.version,
            code_digest=self.code_digest,
            result=self._result
        )
        return digest.digest(c)
