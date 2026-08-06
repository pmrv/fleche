import logging
from dataclasses import dataclass, field, replace
from functools import lru_cache
from typing import Any, Callable, get_type_hints, get_origin, get_args, Annotated
from inspect import Parameter, Signature, signature
from collections.abc import Mapping

from pyiron_snippets.versions import VersionInfo, get_module, get_qualname

from . import digest
from .digest import Digest

logger = logging.getLogger("fleche.call")


class Ignored:
    """
    Type wrapper to mark a function argument as ignored for caching.

    Can be used as a type hint: ``arg: fleche.Ignored`` or ``arg: fleche.Ignored[int]``.
    """

    def __class_getitem__(cls, item):
        return Annotated[item, cls]


class Required:
    """
    Type wrapper to mark a function argument as required for caching.

    Arguments marked as required must be explicitly provided by the caller as keyword
    arguments (i.e.  not via their default value) for the result to be cached.
    This is useful for arguments like random seeds or iteration counts, where
    using the default value might lead to non-deterministic or otherwise
    undesirable caching behavior.

    This is mainly useful when wrapping third-party functions where you do not control
    the default arguments.

    Can be used as a type hint: ``arg: fleche.Required`` or ``arg: fleche.Required[int]``.
    """

    def __class_getitem__(cls, item):
        return Annotated[item, cls]


@dataclass(frozen=True)
class FunctionProfile:
    """All static per-function metadata, cached once per callable."""

    signature: Signature
    qualname: str
    module: str
    version: str | int | None
    code_digest: Digest | None
    ignored: frozenset[str] = field(default_factory=frozenset)
    required: frozenset[str] = field(default_factory=frozenset)

    @classmethod
    def of(cls, func) -> "FunctionProfile":
        """Compute a :class:`FunctionProfile` for *func* without caching."""
        try:
            sig = signature(func)
        except ValueError:
            sig = Signature(parameters=[
                Parameter("args", Parameter.VAR_POSITIONAL),
                Parameter("kwargs", Parameter.VAR_KEYWORD),
            ])

        try:
            info = VersionInfo.of(func)
            qualname = info.qualname or info.module
            module = info.module
            version = getattr(func, "__version__", info.version)
        except ModuleNotFoundError:
            module = get_module(func)
            qualname = get_qualname(func) or module
            version = None

        code_digest = digest.digest(func.__code__) if hasattr(func, "__code__") else None

        try:
            type_hints = get_type_hints(func, include_extras=True)
        except (TypeError, NameError):
            type_hints = {}

        def _is_marker(hint, marker_cls):
            if hint is marker_cls:
                return True
            if get_origin(hint) is Annotated:
                return marker_cls in get_args(hint)
            return False

        ignored = frozenset(name for name, hint in type_hints.items() if _is_marker(hint, Ignored))
        required = frozenset(name for name, hint in type_hints.items() if _is_marker(hint, Required))

        for r in required:
            if r in sig.parameters and sig.parameters[r].kind == sig.parameters[r].POSITIONAL_ONLY:
                logger.warning(
                    "Argument '%s' is marked as Required but is positional-only. Required only works for keyword arguments.",
                    r
                )

        return cls(
            signature=sig,
            qualname=qualname,
            module=module,
            version=version,
            code_digest=code_digest,
            ignored=ignored,
            required=required,
        )

    def strip_for_key(self, bound: dict) -> None:
        """Remove ignored arguments from a bound arguments dict in-place."""
        for ign in self.ignored:
            del bound[ign]

    def check_required(self, args: tuple, kwargs: dict) -> list[str]:
        """Return names of required args not explicitly provided as keyword arguments."""
        if not self.required:
            return []
        bound = self.signature.bind(*args, **kwargs)
        return [r for r in self.required if r not in bound.arguments]


@lru_cache(maxsize=1000)
def _profile(func) -> FunctionProfile:
    return FunctionProfile.of(func)


def _get_profile(func) -> FunctionProfile:
    """Return the :class:`FunctionProfile` for *func*, handling indigestible callables.

    Falls back to the unwrapped function directly when *func* is not
    hashable (i.e. when ``_profile(func)`` raises :exc:`TypeError`).
    """
    try:
        return _profile(func)
    except TypeError:
        return _profile.__wrapped__(func)


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
    p = _get_profile(func)
    sig = p.signature
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
        p = _get_profile(func)
        bound = p.signature.bind(*args, **kwargs)
        bound.apply_defaults()
        return cls(p.qualname, dict(bound.arguments), module=p.module, version=p.version, code_digest=p.code_digest)

    def to_lookup_key(self) -> "Digest":
        # Iterate explicitly in the preserved parameter order; do not sort
        arg_pairs = tuple(self.arguments.items())
        call = replace(self, arguments=arg_pairs, metadata=None, result=None)
        return digest.digest(call)

    def _to_digested(self, save_fn: Callable[[Any], Digest]) -> "DigestedCall":
        """Generic conversion to DigestedCall using *save_fn* to handle each value.

        A ``None`` result stays ``None`` (an incomplete record awaiting its
        result — see :meth:`fleche.caches.BaseCache.prepare`) rather than being
        run through *save_fn*.
        """
        result = None if self.result is None else save_fn(self.result)
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
    # None while the result is still unknown (a record prepared before its
    # function body ran).
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


@dataclass
class PreparedCall:
    """A call admitted to a cache: arguments stored, key sealed, result awaited.

    The middle state of a call's lifecycle, between :class:`Call` (live values,
    nothing stored) and :class:`DigestedCall` (fully recorded).  Created by
    :meth:`fleche.caches.BaseCache.prepare`, which injects the cache whose
    value storage received the arguments; finished by exactly one of
    :meth:`commit` or :meth:`abandon`.

    Also usable as a context manager in synchronous code: leaving the block
    without having committed abandons the call.

    .. code-block:: python

        with cache.prepare(call) as prepared:
            prepared.commit(func(...))       # skipped on exception -> abandoned
    """

    digested: DigestedCall
    cache: Any
    _finished: bool = field(default=False, init=False, repr=False)
    # The live result and metadata between commit and the cache's save;
    # DigestedCall itself only ever holds digests.
    _result: Any = field(default=None, init=False, repr=False)
    _metadata: "dict | None" = field(default=None, init=False, repr=False)

    def commit(self, result: Any, metadata: dict | None = None) -> Digest:
        """Attach *result* and *metadata* to the record and file it.

        The second half of the two-phase save protocol.  The result is handed
        to the cache live, so it is stored *as returned* — including any
        argument the body mutated and passed back out — while the arguments
        keep the digests sealed at prepare time.

        Args:
            result: The function's return value.
            metadata: Optional metadata mapping stored on the record.

        Returns:
            Digest: the record key.

        Raises:
            fleche.caches.Rejected: if the result cannot be stored or the cache
                refuses the record.
            RuntimeError: if this call was already committed or abandoned.
        """
        if self._finished:
            raise RuntimeError("PreparedCall already committed or abandoned")
        self._finished = True
        self._result = result
        if metadata is not None:
            self._metadata = metadata
        return self.cache.save(self)

    def to_lookup_key(self) -> Digest:
        return self.digested.to_lookup_key()

    def resolve(self, result: Digest) -> DigestedCall:
        """Return the final record with the pending result resolved to *result*.

        The shared ending of the two-phase save: the cache stores
        :attr:`_result` wherever its values live and hands the digest back
        here; pending metadata is applied at the same time.
        """
        return replace(
            self.digested,
            result=result,
            metadata=self.digested.metadata if self._metadata is None else self._metadata,
        )

    def abandon(self) -> None:
        """Release the call without recording it.

        Called when the function body raises or its result is not cacheable.
        The default is a no-op: argument values stored by
        :meth:`~fleche.caches.BaseCache.prepare` are content-addressed orphans
        that a later garbage collection sweep reclaims.  Subclasses may hook
        cleanup here.  Idempotent; only :meth:`commit` is barred afterwards.
        """
        self._finished = True

    def __enter__(self) -> "PreparedCall":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        if not self._finished:
            self.abandon()
        return False


class LazyArguments(Mapping):
    def __init__(self, cache, arg_digests):
        self._cache = cache
        self._arg_digests = arg_digests

    def __getitem__(self, key):
        value = self._arg_digests[key]
        if not isinstance(value, Digest):
            return value
        try:
            return self._cache.load_value(value)
        except KeyError:
            # Value not in storage; leave the digest in place.
            return value

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
        if self._result is None:
            return None
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

    def detach(self) -> "DigestedCall":
        """Return the cache-free :class:`DigestedCall` shadow of this :class:`LazyCall`.

        The inverse of :meth:`DigestedCall.fetch`: strips the ``_cache``
        reference so the result can cross process boundaries (e.g. over the
        wire in :mod:`fleche.remote`) without carrying a live cache pointer.
        """
        return DigestedCall(
            name=self.name,
            arguments=dict(self._arguments),
            result=self._result,
            metadata=dict(self.metadata),
            module=self.module,
            version=self.version,
            code_digest=self.code_digest,
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
        p = _get_profile(func)
        bound_args = bind(func, args, kwargs, partial=True)
        # Unspecified arguments default to None (wildcard)
        arguments = {name: bound_args.get(name) for name in p.signature.parameters}
        return cls(p.qualname, arguments, module=p.module, version=p.version)

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
        "FunctionProfile",
        "Ignored",
        "LazyCall",
        "QueryCall",
        "Required",
        "AnyCall"
]
