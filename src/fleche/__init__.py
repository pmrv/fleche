"""lru_cache on 'roids."""

from functools import wraps, partial

from .digest import Unhashable, digest
from .invocation import Invocation
from .metadata import MetaData, Runtime


def fleche(
    _func=None, *, meta: tuple[MetaData] = (Runtime(),)
):

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            try:
                key = digest(Invocation(func.__name__, args, kwargs))
            except Unhashable as e:
                print("WARNING:", e.args[0])
                return func(*args, **kwargs)
            metadata = {m.name: m.pre(*args, **kwargs) for m in meta}
            result = func(*args, **kwargs)
            metadata = {m.name: m.post(metadata[m.name], *args, **kwargs)
                        for m in meta}
            print(key, metadata)
            return result
        return wrapper

    if callable(_func):
        return decorator(_func)
    else:
        return decorator
