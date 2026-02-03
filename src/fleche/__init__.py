"""lru_cache on 'roids."""
from contextlib import contextmanager, AbstractContextManager
from contextvars import ContextVar
from functools import wraps
from pathlib import Path
from typing import Any, Callable, Dict, Optional, TypeVar, Union

from .digest import Unhashable, digest
from .invocation import Invocation
from .metadata import MetaData, Runtime, ResultDigest, PandasDB
from .cache import Cache
from .storage import CloudpickleFileStorage

_T = TypeVar("_T")

_CACHE: ContextVar[Cache] = ContextVar(
    'fleche.CACHE',
    default=Cache(PandasDB({}), CloudpickleFileStorage(Path(".fleche")))
)


def cache(new_cache: Optional[Cache] = None) -> Union[Cache, AbstractContextManager[None]]:
    """
    Manages the active cache for Fleche. If `new_cache` is provided, it returns a context manager
    that sets the cache for the duration of the context. If `new_cache` is None, it returns
    the currently active cache.

    Args:
        new_cache (Optional[Cache]): An optional Cache object to set as the active cache.

    Returns:
        Union[Cache, Callable[..., Any]]: The current Cache object if `new_cache` is None,
                                       otherwise a context manager to set a new cache.
    """
    if new_cache is None:
        return _CACHE.get()

    @contextmanager
    def cache_manager():
        token = _CACHE.set(new_cache)
        try:
            yield
        finally:
            _CACHE.reset(token)
    return cache_manager()


def fleche(
    _func=None, *, meta: tuple[MetaData] = (Runtime(), ResultDigest())
):

    def decorator(func: Callable[..., _T]) -> Callable[..., _T]:
        """
        The actual decorator that wraps the function.
        """
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> _T:
            cache: Cache = _CACHE.get()
            try:
                key: str = digest(Invocation(func.__name__, args, kwargs))
                print(key, Invocation(func.__name__, args, kwargs))
            except Unhashable as e:
                print("WARNING:", e.args[0])
                return func(*args, **kwargs)

            try:
                return cache.storage.load(key)
            except KeyError:
                pass

            metadata = {m.name: m.pre(*args, **kwargs) for m in meta}
            result = func(*args, **kwargs)
            metadata = {m.name: m.post(metadata[m.name], result, *args, **kwargs)
                        for m in meta}
            cache.metadata.save(key, metadata)
            cache.storage.save(key, result)
            return result
        return wrapper

    if callable(_func):
        return decorator(_func)
    else:
        return decorator
