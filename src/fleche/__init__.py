"""lru_cache on 'roids."""

from functools import wraps, partial
from pathlib import Path

from .digest import Unhashable, digest
from .invocation import Invocation
from .metadata import MetaData, Runtime, PandasDB
from .cache import Cache
from .storage import CloudpickleFileStorage

CACHE = Cache(PandasDB({}), CloudpickleFileStorage(Path(".fleche")))


def fleche(
    _func=None, *, meta: tuple[MetaData] = (Runtime(),)
):

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            try:
                key = digest(Invocation(func.__name__, args, kwargs))
                print(key, Invocation(func.__name__, args, kwargs))
            except Unhashable as e:
                print("WARNING:", e.args[0])
                return func(*args, **kwargs)
            metadata = {m.name: m.pre(*args, **kwargs) for m in meta}
            result = func(*args, **kwargs)
            metadata = {m.name: m.post(metadata[m.name], result, *args, **kwargs)
                        for m in meta}
            CACHE.metadata.save(key, metadata)
            CACHE.storage.save(key, result)
            return result
        return wrapper

    if callable(_func):
        return decorator(_func)
    else:
        return decorator
