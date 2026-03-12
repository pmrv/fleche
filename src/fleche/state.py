from contextlib import contextmanager, AbstractContextManager
from contextvars import ContextVar
from typing import Union

from .caches import BaseCache, Cache
from .config import load_cache_config, load_default_metadata
from .metadata import MetaData, Tags

_CACHE: ContextVar[BaseCache] = ContextVar("fleche.CACHE", default=load_cache_config())


def cache(
    new_cache: Union[Cache, str] | None = None, stack=False, sticky=False
) -> Union[BaseCache, AbstractContextManager[None]]:
    """
    Manages the active cache for Fleche. If `new_cache` is provided, it returns a context manager
    that sets the cache for the duration of the context. If `new_cache` is None, it returns
    the currently active cache.

    Args:
        new_cache (Optional[Cache]): An optional Cache object to set as the active cache.
        stack (bool, default False): if True, construct a CacheStack, with new_cache at the bottom
        sticky (bool, default False): if True, permanently set the cache for the current context.

    Returns:
        Union[:class:`.BaseCache`, Callable[..., Any]]:
            The current cache object if `new_cache` is `None`, otherwise a context manager to set a new cache.
    """
    if new_cache is None:
        return _CACHE.get()

    if isinstance(new_cache, str):
        new_cache = load_cache_config(new_cache)
    if not isinstance(new_cache, BaseCache):
        raise ValueError(new_cache)

    if sticky:
        if stack:
            new_cache = _CACHE.get().push(new_cache)
        _CACHE.set(new_cache)
        return new_cache

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


_METADATA: ContextVar[tuple[MetaData, ...]] = ContextVar(
    "fleche.METADATA", default=load_default_metadata()
)


def meta(*new_metadata: MetaData, stack=False, sticky=False):
    """
    A context manager to add metadata to results.

    Args:
        *new_metadata: The metadata to add to the results.
        stack (bool, default False): if True, append to the existing metadata.
        sticky (bool, default False): if True, permanently set the metadata for the current context.
    """
    new_metadata = tuple(new_metadata)
    if stack:
        new_metadata = _METADATA.get() + new_metadata

    if sticky:
        _METADATA.set(new_metadata)
        return new_metadata

    @contextmanager
    def meta_manager():
        token = _METADATA.set(new_metadata)
        try:
            yield
        finally:
            _METADATA.reset(token)

    return meta_manager()


def tags(sticky=False, **kwargs):
    """A context manager to add arbitrary tags to results.

    Args:
        sticky (bool, default False): if True, permanently set the tags for the current context.
        **kwargs: The tags to add to the results.
    """
    return meta(Tags(kwargs), stack=True, sticky=sticky)


def project(name, sticky=False):
    """A context manager to tag results with a project name.

    Args:
        name (str): The name of the project.
        sticky (bool, default False): if True, permanently set the project tag for the current context.
    """
    return tags(project=name, sticky=sticky)
