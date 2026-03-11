import os
from pathlib import Path
from functools import wraps
from inspect import signature
from typing import Any, Callable, Dict, Iterable, TypeVar, Annotated, get_type_hints, get_origin, get_args
from dataclasses import replace
import tempfile
import contextlib
from collections import defaultdict

from . import digest
from . import state
import fleche.metadata as metadata
from .call import Call, AnyCall
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


def process_ignore_required_args(
        func,
        ignore: None | str | Iterable[str] = None,
        require: None | str | Iterable[str] = None,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
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
                logger.warning("Argument '%s' is marked as Required but is positional-only. Required only works for keyword arguments.", r)
    except (TypeError, ValueError):
        pass

    return ignored_args, required_args


def _get_working_directory_root() -> Path:
    """
    Determines the root directory for fleche working directories, following the XDG spec.
    """
    xdg_cache_home = os.environ.get("XDG_CACHE_HOME") or (Path.home() / ".cache")
    root = Path(xdg_cache_home) / "fleche" / "cwd"
    root.mkdir(parents=True, exist_ok=True)
    return root


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
    """

    def decorator(func: Callable[..., _T]) -> Callable[..., _T]:
        """
        The actual decorator that wraps the function.
        """
        if version is not None:
            func.__version__ = version  # ty: ignore

        ignored_args, required_args = process_ignore_required_args(func, ignore, require)
        print(ignored_args, required_args)

        @wraps(func)
        def get_call(*args, partial=False, **kwargs):
            call = Call.from_call(func, *args, partial=partial, **kwargs)
            # drop ignored arguments for the saved call object to make our lives much simpler when hashing or saving it
            # if we leave them in, then Cache.save needs to know about them indirectly to ensure correct digest key
            # generation, but then we'd also have to save it somehow and that just seems bothersome in particular for
            # Sql Callstorage.  We could add a new table there connecting unique functions and their ignored args, but
            # meh.
            for ign in ignored_args:
                del call.arguments[ign]
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
            *args, metadata={}, lazy: bool = False, **kwargs
        ) -> Iterable[AnyCall]:
            """Return matching results from current cache.

            See :class:`CallStorage.query' for details, except that calls returned from here will have their arguments
            and results restored from the value storage via :class:`Cache.query`.

            Args:
                *args, **kwargs: function arguments that should be matched in returned calls; pass `None` as a wildcard
                metadata (dict[str, dict[str, json]]): metadata tags to additionall filter on; if this shadows a
                    function kwargs of the same name, you must pass it by position instead.
                lazy (bool, default False): if True, return lazily loaded call, passed through :meth:`.BaseCache.query`.

            Returns:
                iterable of matching :class:`.Call`
            """
            call = get_call(*args, partial=True, **kwargs)
            if "metadata" in call.arguments:
                logger.warning(
                    "Function argument 'metadata' shadowed by query argument"
                )
            if "lazy" in call.arguments:
                logger.warning("Function argument 'lazy' shadowed by query argument")
            call.metadata = metadata
            return state._CACHE.get().query(call, lazy=lazy)

        _query_doc = _query_func.__doc__
        _query_func = wraps(func)(_query_func)  # ty: ignore

        @wraps(func)
        def _load_func(*args, **kwargs):
            return state._CACHE.get().load(_digest_func(*args, **kwargs)).result

        @wraps(func)
        def _contains_func(*args, **kwargs):
            return state._CACHE.get().contains(_digest_func(*args, **kwargs))

        @wraps(func)
        def _rerun_func(*args, **kwargs):
            """Force execution even if calls (or *any* nested ones) are already present in the cache and overwrite previously saved results."""
            cache: BaseCache = state._CACHE.get()
            with state.cache(RefreshingCache(cache)):
                return wrapper(*args, **kwargs)

        for name, helper, doc_prefix, ret in [
            ("call", get_call, "Get the Call object for", Call),
            ("digest", _digest_func, "Get the cache key for", digest.Digest),
            (
                "query",
                _query_func,
                "Return matching results from current cache for",
                Iterable[Call],
            ),
            ("load", _load_func, "Load result from cache for", None),
            ("contains", _contains_func, "Check if result is in cache for", bool),
            (
                "rerun",
                _rerun_func,
                "Force reevaluation recursively for",
                None,
            ),
        ]:
            helper.__name__ = name
            helper.__qualname__ = f"{helper.__qualname__}.{name}"
            _doc = f"{doc_prefix} {getattr(func, '__name__', 'unknown')}."
            if name == "query":
                _doc += f"\n\n{_query_doc}"
            _doc += f"\n\n{getattr(func, '__doc__', '') or ''}"
            helper.__doc__ = _doc
            helper.__annotations__ = dict(helper.__annotations__)
            if ret:
                helper.__annotations__["return"] = ret

        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> _T:
            missing = [r for r in required_args if r not in kwargs]
            if missing:
                logger.warning(
                    "Missing required keyword arguments for caching: %s", missing
                )
                return func(*args, **kwargs)

            cache: BaseCache = state._CACHE.get()
            try:
                call = get_call(*args, **kwargs)
                key = call.to_lookup_key()
            except digest.Unhashable as e:
                logger.warning("No hash for argument: %s", e.args[0])
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

                expanded_args = tuple(
                    cache.load_value(arg) if isinstance(arg, digest.Digest) else arg
                    for arg in args
                )
                expanded_kwargs = {
                    k: (cache.load_value(v) if isinstance(v, digest.Digest) else v)
                    for k, v in kwargs.items()
                }

                call.result: _T = func(*expanded_args, **expanded_kwargs)
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

        wrapper.call = get_call             # ty: ignore
        wrapper.digest = _digest_func       # ty: ignore
        wrapper.query = _query_func         # ty: ignore
        wrapper.load = _load_func           # ty: ignore
        wrapper.contains = _contains_func   # ty: ignore
        wrapper.rerun = _rerun_func          # ty: ignore
        return wrapper

    if callable(_func):
        return decorator(_func)
    else:
        return decorator


__all__ = [
        "Ignored",
        "Required",
        "fleche",
]
