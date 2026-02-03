"""lru_cache on 'roids."""
from contextlib import contextmanager, AbstractContextManager
from contextvars import ContextVar
from functools import wraps
from pathlib import Path
from typing import Any, Callable, Dict, Optional, TypeVar, Union

from .digest import Unhashable, digest
from .invocation import Invocation
from .metadata import MetaData, PandasDB, Runtime, ResultDigest, InvocationInfo
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


_METADATA: ContextVar[tuple[MetaData]] = ContextVar(
        "fleche.METADATA",
        default=(Runtime(), ResultDigest(), InvocationInfo())
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
                inv = Invocation(func.__name__, args, kwargs)
                if hash_version and hasattr(func, "__version__"):
                    inv.version = func.__version__
                if hash_module and hasattr(func, "__module__"):
                    inv.module = func.__module__
                key: str = digest(inv)
            except Unhashable as e:
                print("WARNING:", e.args[0])
                return func(*args, **kwargs)

            try:
                return cache.storage.load(key)
            except KeyError:
                pass

            active_meta = _METADATA.get() + tuple(meta)
            metadata: Dict[str, Any] = {m.name: m.pre(inv) for m in active_meta}
            result: _T = func(*args, **kwargs)
            metadata = {m.name: m.post(metadata[m.name], result, inv)
                        for m in active_meta}
            cache.save(key, result, metadata)
            return result
        return wrapper

    if callable(_func):
        return decorator(_func)
    else:
        return decorator
