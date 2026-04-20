import os
from pathlib import Path
from functools import wraps
from inspect import signature
from typing import Any, Callable, Dict, Iterable, TypeVar, Annotated, get_type_hints, get_origin, get_args
from dataclasses import dataclass, replace
import tempfile
import contextlib
from collections import defaultdict

from . import digest
from . import state
from . import metadata
from .call import Call, AnyCall, QueryCall, bind
from .caches import Rejected, BaseCache, RefreshingCache


import logging

# make messages from decorator below appear as if from the main module
logger = logging.getLogger("fleche")


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
class ArgumentPolicy:
    """Encapsulates the ignored/required argument policy for a cached function."""

    ignored: frozenset[str]
    required: frozenset[str]

    def strip_for_key(self, bound: dict) -> None:
        """Remove ignored arguments from a bound arguments dict in-place."""
        for ign in self.ignored:
            del bound[ign]

    def check_required(self, func, args: tuple, kwargs: dict) -> list[str]:
        """Return names of required args not explicitly provided as keyword arguments."""
        if not self.required:
            return []
        explicit = set(bind(func, args, kwargs).keys())
        return [r for r in self.required if r not in explicit]


def process_ignore_required_args(
        func,
        ignore: None | str | Iterable[str] = None,
        require: None | str | Iterable[str] = None,
) -> "ArgumentPolicy":
    """Collates arguments that should be ignored/required for caching from explicit arguments and annotations."""

    try:
        hints = get_type_hints(func, include_extras=True)
    except (TypeError, NameError):
        hints = {}

    def is_ignored(hint):
        if hint is Ignored:
            return True
        if get_origin(hint) is Annotated:
            return Ignored in get_args(hint)
        return False

    def is_required(hint):
        if hint is Required:
            return True
        if get_origin(hint) is Annotated:
            return Required in get_args(hint)
        return False

    type_ignored = [name for name, hint in hints.items() if is_ignored(hint)]
    type_required = [name for name, hint in hints.items() if is_required(hint)]

    if ignore is None:
        ignore = ()
    elif isinstance(ignore, str):
        ignore = (ignore,)
    else:
        ignore = tuple(ignore)
    ignored_args = ignore + tuple(type_ignored)

    if require is None:
        require = ()
    elif isinstance(require, str):
        require = (require,)
    else:
        require = tuple(require)
    required_args = require + tuple(type_required)

    try:
        sig = signature(func)
        for r in required_args:
            if r in sig.parameters and sig.parameters[r].kind == sig.parameters[r].POSITIONAL_ONLY:
                logger.warning(
                    "Argument '%s' is marked as Required but is positional-only. Required only works for keyword arguments.",
                    r
                )
    except (TypeError, ValueError):
        pass

    return ArgumentPolicy(ignored=frozenset(ignored_args), required=frozenset(required_args))


def _get_working_directory_root() -> Path:
    """
    Determines the root directory for fleche working directories, following the XDG spec.
    """
    xdg_cache_home = os.environ.get("XDG_CACHE_HOME") or (Path.home() / ".cache")
    root = Path(xdg_cache_home) / "fleche" / "cwd"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _attach(wrapper, fn, *, name, doc_prefix, ret=None, extra_doc=""):
    fn.__name__ = name
    fn.__qualname__ = f"{wrapper.__qualname__}.{name}"
    _doc = f"{doc_prefix} {wrapper.__name__}."
    if extra_doc:
        _doc += f"\n\n{extra_doc}"
    _doc += f"\n\n{wrapper.__doc__ or ''}"
    fn.__doc__ = _doc
    fn.__annotations__ = dict(fn.__annotations__)
    if ret is not None:
        fn.__annotations__["return"] = ret
    setattr(wrapper, name, fn)


_T = TypeVar("_T")

def fleche(
    _func=None,
    *,
    version: int | None = None,
    meta: tuple[metadata.MetaData, ...] = (),
    hash_version: bool = True,
    hash_module: bool = True,
    hash_code: bool = False,
    require: None | str | list[str] | tuple[str] = None,
    ignore: None | str | list[str] | tuple[str] = None,
    isolate: bool = False,
):
    """
    Cache decorator for functions.

    The decorated function is enhanced with helper methods:
    - .call(*args, **kwargs): Get the :clas:`.Call` object.
    - .digest(*args, **kwargs): Get the cache key.
    - .load(*args, **kwargs): Load result from cache.
    - .contains(*args, **kwargs): Check if result is in cache.
    - .rerun(*args, **kwargs): Forces reevaluation recursively.
    The original function is available via .__wrapped__.

    .. warning::

        ``isolate=True`` is **not thread-safe**.  Internally it calls
        :func:`os.chdir`, which is a process-wide POSIX syscall shared by all
        threads.  Concurrent calls with ``isolate=True`` from multiple threads
        will clobber each other's working directory, and a thread may find its
        temporary directory deleted before it has finished using it.

        Use ``isolate=True`` only from a single thread, or run isolated calls
        in separate processes (e.g. via :class:`concurrent.futures.ProcessPoolExecutor`)
        where each process has its own working directory.
    """

    def decorator(func: Callable[..., _T]) -> Callable[..., _T]:
        """
        The actual decorator that wraps the function.
        """
        if version is not None:
            func.__version__ = version  # ty: ignore

        policy = process_ignore_required_args(func, ignore, require)

        @wraps(func)
        def get_call(*args, **kwargs):
            call = Call.from_call(func, *args, **kwargs)
            # drop ignored arguments for the saved call object to make our lives much simpler when hashing or saving it
            # if we leave them in, then Cache.save needs to know about them indirectly to ensure correct digest key
            # generation, but then we'd also have to save it somehow and that just seems bothersome in particular for
            # Sql Callstorage.  We could add a new table there connecting unique functions and their ignored args, but
            # meh.
            policy.strip_for_key(call.arguments)
            if not hash_version:
                call.version = None
            if not hash_module:
                call.module = None
            if not hash_code:
                call.code_digest = None
            return call

        @wraps(func)
        def _digest_func(*args, **kwargs):
            return get_call(*args, **kwargs).to_lookup_key()

        def _query_func(
            *args, metadata={}, **kwargs
        ) -> Iterable[AnyCall]:
            """Return matching results from current cache.

            See :class:`CallStorage.query' for details, except that calls returned from here will have their arguments
            and results restored from the value storage via :class:`Cache.query`.

            Args:
                *args, **kwargs: function arguments that should be matched in returned calls; pass `None` as a wildcard
                metadata (dict[str, dict[str, json]]): metadata tags to additionall filter on; if this shadows a
                    function kwargs of the same name, you must pass it by position instead.

            Returns:
                iterable of matching :class:`.Call`
            """
            call = QueryCall.from_call(func, *args, **kwargs)
            policy.strip_for_key(call.arguments)
            if "metadata" in call.arguments:
                logger.warning(
                    "Function argument 'metadata' shadowed by query argument"
                )
            call.metadata = metadata
            return state._CACHE.get().query(call)

        _query_doc = _query_func.__doc__
        wraps(func)(_query_func)  # ty: ignore

        @wraps(func)
        def _load_func(*args, **kwargs):
            return state._CACHE.get().load(_digest_func(*args, **kwargs)).result

        @wraps(func)
        def _contains_func(*args, **kwargs):
            return state._CACHE.get().contains(_digest_func(*args, **kwargs))

        @wraps(func)
        def _rerun_func(*args, **kwargs):
            cache: BaseCache = state._CACHE.get()
            with state.cache(RefreshingCache(cache)):
                return wrapper(*args, **kwargs)

        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> _T:
            cache: BaseCache = state._CACHE.get()

            # expand args passed as digest early so that everything else below sees the real values
            args = tuple(
                cache.load_value(arg) if isinstance(arg, digest.Digest) else arg
                for arg in args
            )
            kwargs = {
                k: (cache.load_value(v) if isinstance(v, digest.Digest) else v)
                for k, v in kwargs.items()
            }

            try:
                call = get_call(*args, **kwargs)
                key = call.to_lookup_key()
            except digest.Unhashable as e:
                logger.warning("No hash for argument: %s", e.args[0])
                return func(*args, **kwargs)

            missing = policy.check_required(func, args, kwargs)
            if missing:
                logger.warning(
                    "Missing required keyword arguments for caching: %s", missing
                )
                return func(*args, **kwargs)

            try:
                result = cache.load(key).result
                logger.debug("Cache hit for %s with key %s", call.name, key)
                return result
            except KeyError:
                logger.debug("Cache miss for %s with key %s", call.name, key)

            def _run_and_cache():
                active_meta = state._METADATA.get() + tuple(meta)
                metadata: Dict[str, Any] = defaultdict(dict)
                for m in active_meta:
                    metadata[m.name] |= m.pre(replace(call, metadata={}))

                call.result: _T = func(*args, **kwargs)
                if call.result is None:
                    logger.warning("Function returned None, not caching")
                    return None
                for m in active_meta:
                    metadata[m.name] |= m.post(
                        metadata[m.name], replace(call, metadata={})
                    )
                try:
                    call.metadata = metadata
                    logger.debug("Saving result for %s with key %s", call.name, key)
                    cache.save(call)
                except Rejected as e:
                    logger.warning("Cache rejected save: %s", e.args)
                return call.result

            if isolate:
                root = _get_working_directory_root()
                # Create a unique working directory to avoid race conditions during concurrent execution.
                # NOTE: os.chdir is process-wide and not thread-safe.
                with tempfile.TemporaryDirectory(dir=root, prefix=f"{key}_") as workdir:
                    with contextlib.chdir(workdir):
                        return _run_and_cache()
            else:
                return _run_and_cache()

        _attach(wrapper, get_call, name="call", doc_prefix="Get the Call object for", ret=Call)
        _attach(wrapper, _digest_func, name="digest", doc_prefix="Get the cache key for", ret=digest.Digest)
        _attach(wrapper, _query_func, name="query", doc_prefix="Return matching results from current cache for",
                ret=Iterable[Call], extra_doc=_query_doc)
        _attach(wrapper, _load_func, name="load", doc_prefix="Load result from cache for")
        _attach(wrapper, _contains_func, name="contains", doc_prefix="Check if result is in cache for", ret=bool)
        _attach(wrapper, _rerun_func, name="rerun", doc_prefix="Force reevaluation recursively for")
        return wrapper

    if callable(_func):
        return decorator(_func)
    else:
        return decorator


__all__ = [
        "ArgumentPolicy",
        "Ignored",
        "Required",
        "fleche",
]
