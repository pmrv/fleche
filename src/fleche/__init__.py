"""lru_cache on 'roids."""
import os
import logging
from dataclasses import replace
import tempfile
import contextlib
from contextlib import contextmanager, AbstractContextManager
from contextvars import ContextVar
from collections import defaultdict
from functools import wraps
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, Optional, TypeVar, Union

from . import digest
from .digest import Digest
from .call import Call

logger = logging.getLogger("fleche")


def D(d: str) -> Digest:
    """
    Convenience wrapper to create a Digest from a string.

    Digests passed as arguments to @fleche decorated functions are automatically expanded
    to their cached values.
    """
    return Digest(d)
from .metadata import MetaData, Tags
from .caches import BaseCache, Cache, Rejected
from .config import load_cache_config, load_default_metadata

_T = TypeVar("_T")

_CACHE: ContextVar[Cache] = ContextVar(
    'fleche.CACHE',
    default=load_cache_config()
)


def cache(new_cache: Optional[Union[Cache, str]] = None, stack=False) -> Union[Cache, AbstractContextManager[None]]:
    """
    Manages the active cache for Fleche. If `new_cache` is provided, it returns a context manager
    that sets the cache for the duration of the context. If `new_cache` is None, it returns
    the currently active cache.

    Args:
        new_cache (Optional[Cache]): An optional Cache object to set as the active cache.
        stack (bool, default False): if True, construct a CacheStack, with new_cache at the bottom

    Returns:
        Union[Cache, Callable[..., Any]]: The current Cache object if `new_cache` is None,
                                       otherwise a context manager to set a new cache.
    """
    if new_cache is None:
        return _CACHE.get()

    if isinstance(new_cache, str):
        new_cache = load_cache_config(new_cache)
    if not isinstance(new_cache, BaseCache):
        raise ValueError(new_cache)

    @contextmanager
    def cache_manager():
        if stack:
            cache = _CACHE.get().push(new_cache)
        else:
            cache = new_cache
        token = _CACHE.set(cache)
        try:
            yield
        finally:
            _CACHE.reset(token)
    return cache_manager()


_METADATA: ContextVar[tuple[MetaData]] = ContextVar(
    "fleche.METADATA",
    # default=(Runtime(), Digest(), CallInfo())
    default=load_default_metadata()
)


@contextmanager
def metadata(*new_metadata: MetaData, stack=False):
    new_metadata = tuple(new_metadata)
    if stack:
        new_metadata = _METADATA.get() + new_metadata

    token = _METADATA.set(new_metadata)
    try:
        yield
    finally:
        _METADATA.reset(token)


def tags(**kwargs):
    """A context manager to add arbitrary tags to results.

    Args:
        **kwargs: The tags to add to the results.
    """
    return metadata(Tags(kwargs), stack=True)


def project(name):
    """A context manager to tag results with a project name.

    Args:
        name (str): The name of the project.
    """
    return tags(project=name)


def _get_working_directory_root() -> Path:
    """
    Determines the root directory for fleche working directories, following the XDG spec.
    """
    xdg_cache_home = os.environ.get('XDG_CACHE_HOME') or (Path.home() / '.cache')
    root = Path(xdg_cache_home) / 'fleche' / 'cwd'
    root.mkdir(parents=True, exist_ok=True)
    return root


def fleche(
    _func=None,
    *,
    version: int | None = None,
    meta: tuple[MetaData] = (),
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
    - .call(*args, **kwargs): Get the Call object.
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
            func.__version__ = version

        def _ignored_args_tuple() -> tuple[str, ...] | None:
            if ignore is None:
                return ()
            if isinstance(ignore, str):
                return (ignore,)
            return tuple(ignore)

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
            cache: Cache = _CACHE.get()
            try:
                call = get_call(*args, **kwargs)
                key = call.to_lookup_key()
            except digest.Unhashable as e:
                logger.warning("No hash for argument: %s", e.args[0])
                return func(*args, **kwargs)

            try:
                result = cache.load(key).result
                logger.debug("Cache hit for %s with key %s", func.__name__, key)
                return result
            except KeyError:
                logger.debug("Cache miss for %s with key %s", func.__name__, key)

            def _run_and_cache():
                active_meta = _METADATA.get() + tuple(meta)
                metadata: Dict[str, Any] = defaultdict(dict)
                for m in active_meta:
                    metadata[m.name] |= m.pre(replace(call, metadata={}))

                expanded_args = tuple(cache.load_value(arg) if isinstance(arg, Digest) else arg for arg in args)
                expanded_kwargs = {k: (cache.load_value(v) if isinstance(v, Digest) else v) for k, v in kwargs.items()}

                call.result: _T = func(*expanded_args, **expanded_kwargs)
                if call.result is None:
                    logger.warning("Function returned None, not caching")
                    return None
                for m in active_meta:
                    metadata[m.name] |= m.post(metadata[m.name], replace(call, metadata={}))
                try:
                    call.metadata = metadata
                    logger.debug("Saving result for %s with key %s", func.__name__, key)
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

        wrapper.call = get_call

        def _digest_func(*args, **kwargs):
            return get_call(*args, **kwargs).to_lookup_key()

        def _query_func(*args, metadata={}, lazy=False, **kwargs) -> Iterable[Call]:
            """Return matching results from current cache.

            See :class:`CallStorage.query' for details, except that calls returned from here will have their arguments
            and results restored from the value storage via :class:`Cache.query`.

            Args:
                *args, **kwargs: function arguments that should be matched in returned calls; pass `None` as a wildcard
                metadata (dict[str, dict[str, json]]): metadata tags to additionall filter on; if this shadows a
                    function kwargs of the same name, you must pass it by position instead.
                lazy (bool): 

            Returns:
                iterable of matching :class:`.Call`
            """
            call = get_call(*args, partial=True, **kwargs)
            if "metadata" in call.arguments:
                logger.warning("Function argument 'metadata' shadowed by query argument")
            if "lazy" in call.arguments:
                logger.warning("Function argument 'lazy' shadowed by query argument")
            call.metadata = metadata
            return _CACHE.get().query(call, lazy=lazy)

        wrapper.digest = _digest_func
        wrapper.query = _query_func
        wrapper.load = lambda *args, **kwargs: _CACHE.get().load(_digest_func(*args, **kwargs)).result
        wrapper.contains = lambda *args, **kwargs: _CACHE.get().contains(_digest_func(*args, **kwargs))
        return wrapper

    if callable(_func):
        return decorator(_func)
    else:
        return decorator
