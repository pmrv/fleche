from contextlib import AbstractContextManager, ContextDecorator
from contextvars import ContextVar, Token
from typing import Union, Any, TypeVar, Generic, Callable, overload, cast

from .caches import BaseCache, Cache
from .config import load_cache_config, load_default_metadata
from .metadata import MetaData, Tags

_CACHE: ContextVar[BaseCache] = ContextVar("fleche.CACHE", default=load_cache_config())
_METADATA: ContextVar[tuple[MetaData, ...]] = ContextVar(
    "fleche.METADATA", default=load_default_metadata()
)

_T = TypeVar("_T")


class ManagedToken(ContextDecorator, AbstractContextManager, Generic[_T]):
    """A token that manages its own context and can be stuck/plucked.

    This class serves as both a context manager and a decorator. It wraps a
    `ContextVar` and a target value, providing methods to manually activate
    (`.stick()`) and restore (`.pluck()`) the state.
    """

    def __init__(
        self,
        var: ContextVar[_T],
        value: _T,
        resolver: Callable[[_T, _T], _T] | None = None,
    ):
        self.var = var
        self.value = value
        self.resolver = resolver
        self._tokens: ContextVar[tuple[Token[_T], ...]] = ContextVar(
            f"ManagedToken._tokens.{id(self)}", default=()
        )

    def stick(self) -> Token[_T]:
        """Permanently set the context variable to the target value."""
        val_to_set = self.value
        if self.resolver:
            val_to_set = self.resolver(self.var.get(), self.value)

        token = self.var.set(val_to_set)
        self._tokens.set(self._tokens.get() + (token,))
        return token

    def pluck(self):
        """Restore the context variable to its previous state."""
        tokens = self._tokens.get()
        if not tokens:
            raise RuntimeError("Context not active")
        self.var.reset(tokens[-1])
        self._tokens.set(tokens[:-1])

    def __enter__(self):
        self.stick()
        return self

    def __exit__(self, *args):
        self.pluck()


class CacheVar:
    """Wrapper for ContextVar[BaseCache] with enhanced callable interface."""

    def __init__(self, var: ContextVar[BaseCache]):
        self._var = var

    def get(self) -> BaseCache:
        return self._var.get()

    def set(self, value: BaseCache) -> Token[BaseCache]:
        return self._var.set(value)

    def reset(self, token: Union[Token[BaseCache], ManagedToken[BaseCache]]):
        if isinstance(token, ManagedToken):
            token.pluck()
        else:
            self._var.reset(token)

    @overload
    def __call__(self, new_cache: None = None, stack=False) -> BaseCache: ...

    @overload
    def __call__(
        self, new_cache: Union[Cache, str], stack=False
    ) -> ManagedToken[BaseCache]: ...

    def __call__(
        self, new_cache: Union[Cache, str, None] = None, stack=False
    ) -> Union[BaseCache, ManagedToken[BaseCache]]:
        """Manages the active cache for Fleche.

        If `new_cache` is provided, it returns a ManagedToken that can be used
        as a context manager, decorator, or stuck manually. If `new_cache` is
        None, it returns the currently active cache.

        Args:
            new_cache (Optional[Cache]): An optional Cache object to set as the active cache.
            stack (bool, default False): if True, construct a CacheStack, with new_cache at the bottom

        Returns:
            Union[:class:`.BaseCache`, ManagedToken]:
                The current cache object if `new_cache` is `None`, otherwise a context manager to set a new cache.
        """
        if new_cache is None:
            return self.get()

        resolved_cache: BaseCache
        if isinstance(new_cache, str):
            resolved_cache = load_cache_config(new_cache)
        elif isinstance(new_cache, BaseCache):
            resolved_cache = new_cache
        else:
            raise ValueError(new_cache)

        resolver = (lambda current, new: current.push(new)) if stack else None
        return ManagedToken(self._var, resolved_cache, resolver)


class MetaVar:
    """Wrapper for ContextVar[tuple[MetaData, ...]] with enhanced callable interface."""

    def __init__(self, var: ContextVar[tuple[MetaData, ...]]):
        self._var = var

    def get(self) -> tuple[MetaData, ...]:
        return self._var.get()

    def set(self, value: tuple[MetaData, ...]) -> Token[tuple[MetaData, ...]]:
        return self._var.set(value)

    def reset(
        self,
        token: Union[Token[tuple[MetaData, ...]], ManagedToken[tuple[MetaData, ...]]],
    ):
        if isinstance(token, ManagedToken):
            token.pluck()
        else:
            self._var.reset(token)

    @overload
    def __call__(self, stack=False) -> tuple[MetaData, ...]: ...

    @overload
    def __call__(
        self, *new_metadata: MetaData, stack=False
    ) -> ManagedToken[tuple[MetaData, ...]]: ...

    def __call__(
        self, *new_metadata: MetaData, stack=False
    ) -> Union[tuple[MetaData, ...], ManagedToken[tuple[MetaData, ...]]]:
        """A context manager to add metadata to results.

        Args:
            *new_metadata: The metadata to add to the results.
            stack (bool, default False): if True, append to the existing metadata.
        """
        if not new_metadata:
            return self.get()

        resolved_meta = tuple(new_metadata)
        resolver = (lambda current, new: current + new) if stack else None

        return ManagedToken(self._var, resolved_meta, resolver)


cache = CacheVar(_CACHE)
meta = MetaVar(_METADATA)


def tags(**kwargs) -> ManagedToken[tuple[MetaData, ...]]:
    """A context manager to add arbitrary tags to results.

    Args:
        **kwargs: The tags to add to the results.
    """
    return cast(ManagedToken[tuple[MetaData, ...]], meta(Tags(kwargs), stack=True))


def project(name) -> ManagedToken[tuple[MetaData, ...]]:
    """A context manager to tag results with a project name.

    Args:
        name (str): The name of the project.
    """
    return tags(project=name)
