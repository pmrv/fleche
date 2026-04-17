from contextlib import contextmanager, AbstractContextManager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import overload, Iterator, Callable

from . import caches, config, metadata

_CACHE: ContextVar[caches.BaseCache] = ContextVar("fleche.CACHE", default=config.load_cache_config())


@overload
def cache(new_cache: None = None, stack: bool = False) -> caches.BaseCache: ...


@overload
def cache(
    new_cache: caches.BaseCache | str, stack: bool = False
) -> AbstractContextManager[None]: ...


def cache(
    new_cache: caches.BaseCache | str | None = None, stack: bool = False
) -> caches.BaseCache | AbstractContextManager[None]:
    """
    Manages the active cache for Fleche. If `new_cache` is provided, it returns a context manager
    that sets the cache for the duration of the context. If `new_cache` is None, it returns
    the currently active cache.

    Args:
        new_cache (Optional[BaseCache]): An optional Cache object to set as the active cache.
        stack (bool, default False): if True, construct a CacheStack, with new_cache at the bottom

    Returns:
        Union[:class:`.BaseCache`, AbstractContextManager[None]]:
            The current cache object if `new_cache` is `None`, otherwise a context manager to set a new cache.
    """
    if new_cache is None:
        return _CACHE.get()

    if isinstance(new_cache, str):
        new_cache = config.load_cache_config(new_cache)
    if not isinstance(new_cache, caches.BaseCache):
        raise ValueError(new_cache)

    @contextmanager
    def cache_manager() -> Iterator[None]:
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


_METADATA: ContextVar[tuple[metadata.MetaData, ...]] = ContextVar(
    "fleche.METADATA", default=config.load_default_metadata()
)


@contextmanager
def meta(*new_metadata: metadata.MetaData, stack=False):
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
    return meta(metadata.Tags(kwargs), stack=True)


def project(name):
    """A context manager to tag results with a project name.

    Args:
        name (str): The name of the project.
    """
    return tags(project=name)


@dataclass(frozen=True, eq=True)
class BoundWrapper:
    """Utility class that freezes global state for the cache and metadata config.

    Essentially acts like an early binding closure.

    This is intended to enable passing around fleche-decorated functions in pickled form by baking in the state into the
    pickle on request."""

    func: Callable
    cache: caches.BaseCache
    meta: tuple[metadata.MetaData, ...]

    @classmethod
    def bind(cls, func):
        """Bind cache and metadata state.

        Returns a new callable that will behave always as if run under the context under which :meth:`.bind()` was
        originally called.

        Args:
            func (callable): any callable; plain functions that only call fleche-wrapped ones are explicitly allowed

        Returns:
            :class:`.BoundWrapper`: instance with the bound cache and metadata state"""
        return cls(func, _CACHE.get(), _METADATA.get())

    def __call__(self, *args, **kwargs):
        token_cache = _CACHE.set(self.cache)
        token_meta = _METADATA.set(self.meta)
        try:
            return self.func(*args, **kwargs)
        finally:
            _METADATA.reset(token_meta)
            _CACHE.reset(token_cache)
