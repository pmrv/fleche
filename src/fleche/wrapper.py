import os
from pathlib import Path
from functools import wraps
from typing import Any, Callable, Dict, Iterable, TypeVar
from dataclasses import replace
import tempfile
import contextlib
from collections import defaultdict

from . import digest
from . import state
import fleche.metadata as metadata
from .call import Call, AnyCall
from .caches import Rejected, BaseCache


import logging

# make messages from decorator below appear as if from the main module
logger = logging.getLogger("fleche")


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
    The original function is available via .__wrapped__.
    """

    def decorator(func: Callable[..., _T]) -> Callable[..., _T]:
        """
        The actual decorator that wraps the function.
        """
        if version is not None:
            func.__version__ = version  # ty: ignore

        def _ignored_args_tuple() -> tuple[str, ...]:
            if ignore is None:
                return ()
            if isinstance(ignore, str):
                return (ignore,)
            return tuple(ignore)

        @wraps(func)
        def get_call(*args, partial=False, **kwargs):
            call = Call.from_call(func, *args, partial=partial, **kwargs)
            # drop ignored arguments for the saved call object to make our lives much simpler when hashing or saving it
            # if we leave them in, then Cache.save needs to know about them indirectly to ensure correct digest key
            # generation, but then we'd also have to save it somehow and that just seems bothersome in particular for
            # Sql Callstorage.  We could add a new table there connecting unique functions and their ignored args, but
            # meh.
            for ign in _ignored_args_tuple():
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
            return state.cache.query(call, lazy=lazy)

        _query_doc = _query_func.__doc__
        _query_func = wraps(func)(_query_func)  # ty: ignore

        @wraps(func)
        def _load_func(*args, **kwargs):
            return state.cache.load(_digest_func(*args, **kwargs)).result

        @wraps(func)
        def _contains_func(*args, **kwargs):
            return state.cache.contains(_digest_func(*args, **kwargs))

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
            if require is None:
                required_args = ()
            elif isinstance(require, str):
                required_args = (require,)
            else:
                required_args = require
            if any(r not in kwargs for r in required_args):
                logger.warning("Missing required argument: %s", required_args)
                return func(*args, **kwargs)
            cache = state.cache
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
                active_meta = tuple(state.meta) + tuple(meta)
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
        return wrapper

    if callable(_func):
        return decorator(_func)
    else:
        return decorator
