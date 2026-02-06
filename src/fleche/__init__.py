"""lru_cache on 'roids."""
from contextlib import contextmanager, AbstractContextManager
from contextvars import ContextVar
from collections import defaultdict
from functools import wraps
from pathlib import Path
from typing import Any, Callable, Dict, Optional, TypeVar, Union

from .digest import Unhashable, digest
from .invocation import Invocation
from .metadata import MetaData, PandasDB, Runtime, Digest, InvocationInfo, Tags
from .cache import Cache, SaveError
from . import storage

_T = TypeVar("_T")

_CACHE: ContextVar[Cache] = ContextVar(
    'fleche.CACHE',
    default=Cache(storage.CloudpickleFile(Path(".fleche"))).metadb(PandasDB({}))
)


def cache(new_cache: Optional[Cache] = None, stack=False) -> Union[Cache, AbstractContextManager[None]]:
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
    default=(Runtime(), Digest(), InvocationInfo())
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


def fleche(
    _func=None,
    *,
    version: int | None = None,
    meta: tuple[MetaData] = (),
    hash_version: bool = True,
    hash_module: bool = True
):

    def decorator(func: Callable[..., _T]) -> Callable[..., _T]:
        """
        The actual decorator that wraps the function.
        """
        if version is not None:
            func.__version__ = version

        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> _T:
            cache: Cache = _CACHE.get()
            try:
                inv = Invocation.from_call(func, *args, **kwargs)
                if not hash_version:
                    inv.version = None
                if not hash_module:
                    inv.module = None
                key: str = digest(inv)
            except Unhashable as e:
                print("WARNING NO HASH:", e.args[0])
                return func(*args, **kwargs)

            try:
                return cache.load(cache.load(key)[0])
            except KeyError:
                pass

            active_meta = _METADATA.get() + tuple(meta)
            metadata: Dict[str, Any] = defaultdict(dict)
            for m in active_meta:
                metadata[m.name] |= m.pre(inv)
            result: _T = func(*args, **kwargs)
            for m in active_meta:
                metadata[m.name] |= m.post(metadata[m.name], result, inv)
            try:
                cache.save(inv, result, dict(metadata))
            except SaveError as e:
                print("WARNING NO SAVE:", *e.args)
            return result
        return wrapper

    if callable(_func):
        return decorator(_func)
    else:
        return decorator
