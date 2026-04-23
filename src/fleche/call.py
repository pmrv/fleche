import logging
from dataclasses import dataclass, field, replace
from typing import Any, Callable
from inspect import signature
from collections.abc import Mapping

from pyiron_snippets.versions import VersionInfo, get_module, get_qualname

from . import digest
from .digest import Digest

logger = logging.getLogger("fleche.call")


def _extract_version_info(func) -> tuple[str, str, str | int | None]:
    """Extract ``(name, module, version)`` from ``func`` via :mod:`pyiron_snippets.versions`.

    Uses :meth:`VersionInfo.of` to introspect ``func``.  When the module is not
    importable, falls back to attribute inspection without a version.  A ``__version__``
    attribute set directly on ``func`` takes priority over the module-level version.
    """
    try:
        info = VersionInfo.of(func)
    except ModuleNotFoundError:
        module = get_module(func)
        name = get_qualname(func) or module
        return name, module, None
    name = info.qualname or info.module
    version = getattr(func, "__version__", info.version)
    return name, info.module, version


def bind(func, args, kwargs, apply_defaults=False, partial=False):
    """Thin wrapper around :meth:`inspect.Signature.bind` / :meth:`~inspect.Signature.bind_partial`.

    Args:
        func: The callable whose signature to bind against.
        args: Positional arguments.
        kwargs: Keyword arguments.
        apply_defaults: If ``True``, fill in default values for parameters
            that were not explicitly supplied.
        partial: If ``True``, use :meth:`~inspect.Signature.bind_partial`,
            which allows required arguments to be omitted (treated as wildcards).

    Returns:
        :attr:`inspect.BoundArguments.arguments` — an ``OrderedDict``
        containing the supplied (and, when requested, defaulted) values.
    """
    sig = signature(func)
    if partial:
        bound = sig.bind_partial(*args, **kwargs)
    else:
        bound = sig.bind(*args, **kwargs)
    if apply_defaults:
        bound.apply_defaults()
    return bound.arguments


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
    version: str | int | None = None
    code_digest: str | None = None
    result: Any = None

    @classmethod
    def from_call(cls, func, *args, **kwargs):
        arguments = dict(bind(func, args, kwargs, apply_defaults=True))
        qualname, module, version = _extract_version_info(func)
        call = cls(qualname, arguments, module=module)
        call.version = getattr(func, "__version__", version)
        if hasattr(func, "__code__"):
            call.code_digest = digest.digest(func.__code__)
        return call

    def to_lookup_key(self) -> "Digest":
        # Iterate explicitly in the preserved parameter order; do not sort
        arg_pairs = tuple(self.arguments.items())
        call = replace(self, arguments=arg_pairs, metadata=None, result=None)
        return digest.digest(call)

    def _to_digested(self, save_fn: Callable[[Any], Digest]) -> "DigestedCall":
        """Generic conversion to DigestedCall using *save_fn* to handle each value."""
        result = save_fn(self.result)
        arguments: dict[str, Digest] = {}
        for k, v in self.arguments.items():
            if isinstance(v, Digest):
                arguments[k] = v
            else:
                try:
                    arguments[k] = save_fn(v)
                except Exception as exc:
                    from .storage.base import SaveError  # lazy import: storage.base depends on call
                    if not isinstance(exc, SaveError):
                        raise
                    logger.warning("Failed to save argument %r: falling back to digest-only reference", k)
                    arguments[k] = digest.digest(v)
        return DigestedCall(
            name=self.name,
            arguments=arguments,
            result=result,
            metadata=self.metadata,
            module=self.module,
            version=self.version,
            code_digest=self.code_digest,
        )

    def stash(self, values) -> "DigestedCall":
        """Save arguments and result into *values*, returning a :class:`DigestedCall`.

        Result save errors propagate to the caller.  Argument save errors fall back
        to a digest-only reference (the value is hashed but not stored).

        Args:
            values: A :class:`~fleche.storage.ValueStorage` instance to persist values into.

        Returns:
            A :class:`DigestedCall` with all argument values and the result replaced by
            their :class:`~fleche.digest.Digest` keys.

        See Also:
            :meth:`digest` for a variant that does not write to storage.
        """
        return self._to_digested(values.save)

    def digest(self) -> "DigestedCall":
        """Digest arguments and result without saving to storage, returning a :class:`DigestedCall`.

        Equivalent to :meth:`stash` but uses :func:`~fleche.digest.digest` instead of
        ``values.save``, so no data is written anywhere.
        """
        return self._to_digested(digest.digest)


@dataclass
class DigestedCall:
    """A Call where arguments and result are :class:`~fleche.digest.Digest` pointers into a value store.

    Produced by :meth:`Call.stash` or :meth:`Call.digest`; represents a call whose values have been
    replaced by their content-addressed keys.
    """

    name: str
    arguments: dict[str, "digest.Digest"]
    result: "digest.Digest | None" = None
    metadata: dict[str, dict[str, Any]] = field(default_factory=dict)
    module: str | None = None
    version: str | int | None = None
    code_digest: str | None = None

    def __eq__(self, other: object) -> bool:
        # DigestedCall and Call with identical field values are semantically equivalent.
        if not isinstance(other, (DigestedCall, Call)):
            return NotImplemented
        return (
            self.name == other.name
            and self.arguments == other.arguments
            and self.result == other.result
            and self.metadata == other.metadata
            and self.module == other.module
            and self.version == other.version
            and self.code_digest == other.code_digest
        )

    def __digest__(self):
        # DigestedCall must hash identically to the equivalent Call with the same fields,
        # so that digest(DigestedCall) == digest(LazyCall) == digest(Call-with-digest-args).
        c = Call(
            name=self.name,
            arguments=self.arguments,
            metadata=self.metadata,
            module=self.module,
            version=self.version,
            code_digest=self.code_digest,
            result=self.result,
        )
        return digest.digest(c)

    def to_lookup_key(self) -> "Digest":
        # Independent implementation: build a Call directly without calling Call.to_lookup_key.
        # digest(Digest(x)) == x, so digested argument values hash identically to their originals.
        arg_pairs = tuple(self.arguments.items())
        c = Call(name=self.name, arguments={}, module=self.module, version=self.version, code_digest=self.code_digest)
        return digest.digest(replace(c, arguments=arg_pairs, result=None, metadata=None))

    def fetch(self, cache) -> "LazyCall":
        """Wrap this :class:`DigestedCall` in a :class:`LazyCall` backed by *cache*.

        Args:
            cache: A cache instance (e.g. :class:`~fleche.caches.Cache`) whose value
                storage will be used to load argument and result values on demand.

        Returns:
            A :class:`LazyCall` that loads values lazily from *cache*.
        """
        return LazyCall(
            name=self.name,
            _arguments=self.arguments,
            _result=self.result,
            _cache=cache,
            metadata=self.metadata,
            module=self.module,
            version=self.version,
            code_digest=self.code_digest,
        )


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
    version: str | int | None = None
    code_digest: str | None = None

    @property
    def arguments(self):
        return LazyArguments(self._cache, self._arguments)

    @property
    def result(self):
        return self._cache.load_value(self._result)

    def to_lookup_key(self) -> str:
        return DigestedCall(
            name=self.name,
            arguments=self._arguments,
            module=self.module,
            version=self.version,
            code_digest=self.code_digest,
        ).to_lookup_key()

    def fetch(self) -> Call:
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


AnyQueryType = None | digest.Digest | Any
StrQueryType = None | digest.Digest | str

@dataclass
class QueryCall:
    name: StrQueryType = None
    arguments: dict[str, AnyQueryType] | None = None
    metadata: dict[str, dict[str, StrQueryType]] | None = None
    module: str | None = None
    version: str | int | None = None
    code_digest: digest.Digest | None = None
    result: AnyQueryType = None

    @classmethod
    def from_call(cls, func, *args, **kwargs):
        bound_args = bind(func, args, kwargs, partial=True)
        # Unspecified arguments default to None (wildcard)
        arguments = {name: bound_args.get(name) for name in signature(func).parameters}
        qualname, module, version = _extract_version_info(func)
        call = cls(qualname, arguments, module=module)
        call.version = getattr(func, "__version__", version)
        return call

    def matches(self, other: 'Call | LazyCall | DigestedCall') -> bool:
        """Check if this call matches another call, treating None as a wildcard in this object."""
        def none_or_equal(a, b):
            if a is None:
                return True
            # Use digest to handle both raw values and Digest objects consistently
            return digest.digest(a) == digest.digest(b)

        if not none_or_equal(self.name, other.name):
            return False
        if not none_or_equal(self.module, other.module):
            return False
        if not none_or_equal(self.version, other.version):
            return False
        if not none_or_equal(self.code_digest, other.code_digest):
            return False
        if not none_or_equal(self.result, other.result):
            return False

        if self.arguments is not None:
            for k, v in self.arguments.items():
                if k not in other.arguments:
                    return False
                if not none_or_equal(v, other.arguments[k]):
                    return False

        if self.metadata:
            for mname, filters in self.metadata.items():
                data = other.metadata.get(mname)
                if data is None:
                    return False
                for kk, vv in (filters or {}).items():
                    if vv is None:
                        if kk not in data:
                            return False
                    else:
                        if data.get(kk) != vv:
                            return False
        return True


AnyCall = Call | LazyCall


__all__ = [
        "bind",
        "Call",
        "DigestedCall",
        "LazyCall",
        "QueryCall",
        "AnyCall"
]
