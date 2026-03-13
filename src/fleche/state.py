from contextlib import AbstractContextManager, ContextDecorator
from contextvars import ContextVar, Token
from typing import Union, Any, TypeVar, Generic, Callable, overload, cast, Iterable
import pandas as pd

from .caches import BaseCache, Cache, CacheStack, FilteredCache
from .config import load_cache_config, load_default_metadata
from .metadata import MetaData, Tags
from .digest import Digest
from .call import Call, LazyCall

# Define internal context variables at the top to ensure they are available for all classes
_CACHE: ContextVar[BaseCache] = ContextVar("fleche.CACHE", default=load_cache_config())
_METADATA: ContextVar[tuple[MetaData, ...]] = ContextVar(
    "fleche.METADATA", default=load_default_metadata()
)

_T = TypeVar("_T")


class CacheContext(BaseCache, ContextDecorator, AbstractContextManager):
    """A context manager and decorator for setting the active cache."""

    def __init__(self, cache_var: "CacheVar", new_cache: BaseCache, stack: bool = False):
        self._cache_var = cache_var
        self._new_cache = new_cache
        self._stack = stack
        self._token: Token[BaseCache] | None = None

    def __enter__(self):
        val_to_set = self._new_cache
        if self._stack:
            val_to_set = self._cache_var.get().push(self._new_cache)
        self._token = self._cache_var.set(val_to_set)
        return self._new_cache

    def __exit__(self, *args):
        if self._token:
            self._cache_var.reset(self._token)
            self._token = None

    # BaseCache proxy methods - they refer to the cache this context *would* set or currently represents
    def save(self, call: Call) -> str:
        return self._new_cache.save(call)

    @overload
    def load(self, key: str, lazy: bool = False) -> Call: ...

    @overload
    def load(self, key: str, lazy: bool = True) -> LazyCall: ...

    def load(self, key: str, lazy: bool = False) -> Call | LazyCall:
        return self._new_cache.load(key, lazy=lazy)

    def load_value(self, key: str) -> Any:
        return self._new_cache.load_value(key)

    def contains(self, key: str) -> bool:
        return self._new_cache.contains(key)

    def push(self, cache: BaseCache) -> CacheStack:
        return self._new_cache.push(cache)

    def shrink(self, key: Digest | str) -> Digest:
        return self._new_cache.shrink(key)

    def query(self, call: Call, lazy: bool = False) -> Iterable[Call | LazyCall]:
        return self._new_cache.query(call, lazy=lazy)

    def table(self) -> pd.DataFrame:
        return self._new_cache.table()

    def filter(self, predicate: Callable[[Call | LazyCall], bool] | Call) -> FilteredCache:
        return self._new_cache.filter(predicate)


class CacheVar(BaseCache):
    """A proxy for the active cache that also manages context switching."""

    def __init__(self, var: ContextVar[BaseCache]):
        self._var = var

    def get(self) -> BaseCache:
        return self._var.get()

    def set(self, value: BaseCache) -> Token[BaseCache]:
        return self._var.set(value)

    def reset(self, token: Token[BaseCache]):
        self._var.reset(token)

    # BaseCache implementation via delegation to the current context
    def save(self, call: Call) -> str:
        return self._var.get().save(call)

    @overload
    def load(self, key: str, lazy: bool = False) -> Call: ...

    @overload
    def load(self, key: str, lazy: bool = True) -> LazyCall: ...

    def load(self, key: str, lazy: bool = False) -> Call | LazyCall:
        return self._var.get().load(key, lazy=lazy)

    def load_value(self, key: str) -> Any:
        return self._var.get().load_value(key)

    def contains(self, key: str) -> bool:
        return self._var.get().contains(key)

    def push(self, cache: BaseCache) -> CacheStack:
        return self._var.get().push(cache)

    def shrink(self, key: Digest | str) -> Digest:
        return self._var.get().shrink(key)

    def query(self, call: Call, lazy: bool = False) -> Iterable[Call | LazyCall]:
        return self._var.get().query(call, lazy=lazy)

    def table(self) -> pd.DataFrame:
        return self._var.get().table()

    def filter(self, predicate: Callable[[Call | LazyCall], bool] | Call) -> FilteredCache:
        return self._var.get().filter(predicate)

    @overload
    def __call__(self, new_cache: None = None, stack: bool = False, sticky: bool = False) -> BaseCache: ...

    @overload
    def __call__(
        self, new_cache: Union[BaseCache, str], stack: bool = False, sticky: bool = False
    ) -> Union[BaseCache, CacheContext]: ...

    def __call__(
        self, new_cache: Union[BaseCache, str, None] = None, stack: bool = False, sticky: bool = False
    ) -> Union[BaseCache, CacheContext]:
        if new_cache is None:
            return self.get()

        resolved_cache: BaseCache
        if isinstance(new_cache, str):
            resolved_cache = load_cache_config(new_cache)
        elif isinstance(new_cache, BaseCache):
            resolved_cache = new_cache
        else:
            raise ValueError(new_cache)

        if sticky:
            val_to_set = resolved_cache
            if stack:
                val_to_set = self.get().push(resolved_cache)
            self.set(val_to_set)
            return val_to_set

        return CacheContext(self, resolved_cache, stack)


class MetaContext(ContextDecorator, AbstractContextManager):
    """A context manager and decorator for adding metadata."""

    def __init__(self, meta_var: "MetaVar", new_metadata: tuple[MetaData, ...], stack: bool = False):
        self._meta_var = meta_var
        self._new_metadata = new_metadata
        self._stack = stack
        self._token: Token[tuple[MetaData, ...]] | None = None

    def __enter__(self):
        val_to_set = self._new_metadata
        if self._stack:
            val_to_set = self._meta_var.get() + self._new_metadata
        self._token = self._meta_var.set(val_to_set)
        return val_to_set

    def __exit__(self, *args):
        if self._token:
            self._meta_var.reset(self._token)
            self._token = None


class MetaVar:
    """A proxy for the active metadata that also manages context switching."""

    def __init__(self, var: ContextVar[tuple[MetaData, ...]]):
        self._var = var

    def get(self) -> tuple[MetaData, ...]:
        return self._var.get()

    def set(self, value: tuple[MetaData, ...]) -> Token[tuple[MetaData, ...]]:
        return self._var.set(value)

    def reset(self, token: Token[tuple[MetaData, ...]]):
        self._var.reset(token)

    # Sequence-like interface
    def __iter__(self):
        return iter(self.get())

    def __len__(self):
        return len(self.get())

    def __getitem__(self, index):
        return self.get()[index]

    @overload
    def __call__(self, stack: bool = False, sticky: bool = False) -> tuple[MetaData, ...]: ...

    @overload
    def __call__(
        self, *new_metadata: MetaData, stack: bool = False, sticky: bool = False
    ) -> Union[tuple[MetaData, ...], MetaContext]: ...

    def __call__(
        self, *new_metadata: MetaData, stack: bool = False, sticky: bool = False
    ) -> Union[tuple[MetaData, ...], MetaContext]:
        if not new_metadata:
            return self.get()

        resolved_meta = tuple(new_metadata)

        if sticky:
            val_to_set = resolved_meta
            if stack:
                val_to_set = self.get() + resolved_meta
            self.set(val_to_set)
            return val_to_set

        return MetaContext(self, resolved_meta, stack)


cache = CacheVar(_CACHE)
meta = MetaVar(_METADATA)


def tags(sticky: bool = False, **kwargs) -> Union[tuple[MetaData, ...], MetaContext]:
    """A context manager to add arbitrary tags to results.

    Args:
        sticky (bool, default False): if True, permanently add the tags.
        **kwargs: The tags to add to the results.
    """
    return meta(Tags(kwargs), stack=True, sticky=sticky)


def project(name, sticky: bool = False) -> Union[tuple[MetaData, ...], MetaContext]:
    """A context manager to tag results with a project name.

    Args:
        name (str): The name of the project.
        sticky (bool, default False): if True, permanently add the project tag.
    """
    return tags(sticky=sticky, project=name)
