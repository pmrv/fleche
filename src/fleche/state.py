from contextlib import contextmanager, AbstractContextManager, ContextDecorator
from contextvars import ContextVar, Token
from typing import Union, Any, TypeVar, Generic, Callable

from .caches import BaseCache, Cache
from .config import load_cache_config, load_default_metadata
from .metadata import MetaData, Tags

_CACHE: ContextVar[BaseCache] = ContextVar("fleche.CACHE", default=load_cache_config())

_T = TypeVar("_T")

class StickyContext(ContextDecorator, AbstractContextManager, Generic[_T]):
    def __init__(
        self,
        var: ContextVar[_T],
        value: _T,
        resolver: Callable[[_T, _T], _T] | None = None,
    ):
        self.var = var
        self.value = value
        self.resolver = resolver
        self._tokens: ContextVar[list[Token[_T]]] = ContextVar(
            f"StickyContext.{id(self)}"
        )

    def stick(self):
        val_to_set = self.value
        if self.resolver:
            val_to_set = self.resolver(self.var.get(), self.value)

        try:
            tokens = self._tokens.get()
        except LookupError:
            tokens = []
            self._tokens.set(tokens)
        tokens.append(self.var.set(val_to_set))

    def pluck(self):
        try:
            tokens = self._tokens.get()
        except LookupError:
            raise RuntimeError("Context not active")
        if not tokens:
            raise RuntimeError("Context not active")
        self.var.reset(tokens.pop())

    def __enter__(self):
        self.stick()
        return self

    def __exit__(self, *args):
        self.pluck()


def cache(
    new_cache: Union[Cache, str] | None = None, stack=False
) -> Union[BaseCache, StickyContext[BaseCache]]:
    """
    Manages the active cache for Fleche. If `new_cache` is provided, it returns a context manager
    that sets the cache for the duration of the context. If `new_cache` is None, it returns
    the currently active cache.

    Args:
        new_cache (Optional[Cache]): An optional Cache object to set as the active cache.
        stack (bool, default False): if True, construct a CacheStack, with new_cache at the bottom

    Returns:
        Union[:class:`.BaseCache`, StickyContext]:
            The current cache object if `new_cache` is `None`, otherwise a context manager to set a new cache.
    """
    if new_cache is None:
        return _CACHE.get()

    resolved_cache: BaseCache
    if isinstance(new_cache, str):
        resolved_cache = load_cache_config(new_cache)
    elif isinstance(new_cache, BaseCache):
        resolved_cache = new_cache
    else:
        raise ValueError(new_cache)

    resolver = (lambda current, new: current.push(new)) if stack else None
    return StickyContext(_CACHE, resolved_cache, resolver)


_METADATA: ContextVar[tuple[MetaData, ...]] = ContextVar(
    "fleche.METADATA", default=load_default_metadata()
)


def meta(*new_metadata: MetaData, stack=False) -> StickyContext[tuple[MetaData, ...]]:
    """
    A context manager to add metadata to results.

    Args:
        *new_metadata: The metadata to add to the results.
        stack (bool, default False): if True, append to the existing metadata.
    """
    resolved_meta = tuple(new_metadata)
    resolver = (lambda current, new: current + new) if stack else None

    return StickyContext(_METADATA, resolved_meta, resolver)


def tags(**kwargs) -> StickyContext[tuple[MetaData, ...]]:
    """A context manager to add arbitrary tags to results.

    Args:
        **kwargs: The tags to add to the results.
    """
    return meta(Tags(kwargs), stack=True)


def project(name) -> StickyContext[tuple[MetaData, ...]]:
    """A context manager to tag results with a project name.

    Args:
        name (str): The name of the project.
    """
    return tags(project=name)
