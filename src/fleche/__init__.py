"""lru_cache on 'roids."""
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
from pathlib import Path

from .digest import Unhashable, digest
from .invocation import Invocation
from .metadata import MetaData, Runtime, ResultDigest, PandasDB
from .cache import Cache
from .storage import CloudpickleFileStorage

_CACHE: ContextVar[Cache] = ContextVar(
    'fleche.CACHE',
    default=Cache(PandasDB({}), CloudpickleFileStorage(Path(".fleche")))
)


def cache(new_cache: Cache | None = None):
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

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            cache = _CACHE.get()
            try:
                key = digest(Invocation(func.__name__, args, kwargs))
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
