from contextlib import AbstractContextManager
import contextvars
from contextvars import ContextVar, Token
from dataclasses import dataclass
from types import SimpleNamespace
from typing import overload, Callable

from . import caches, config, metadata

_CACHE: ContextVar[caches.BaseCache] = ContextVar("fleche.CACHE", default=config.load_cache_config())


class _StickyContext:
    """Context manager for sticky ContextVar state.

    The value is set immediately on construction; entering the ``with``-block is a
    no-op, and exiting restores the previous value via the stored token.

    In Python 3.14+, ``Token`` objects returned by ``ContextVar.set()`` support the
    context manager protocol natively, making this class unnecessary.  It serves as
    a backport for earlier Python versions.
    """

    __slots__ = ("_var", "_token")

    def __init__(self, var: ContextVar, token: Token) -> None:
        self._var = var
        self._token = token

    def __enter__(self) -> None:
        return None

    def __exit__(self, *args: object) -> None:
        self._var.reset(self._token)


@overload
def cache(new_cache: None = None, stack: bool = False) -> caches.BaseCache: ...


@overload
def cache(
    new_cache: caches.BaseCache | str, stack: bool = False
) -> AbstractContextManager[None]: ...


def cache(
    new_cache: caches.BaseCache | str | None = None, stack: bool = False
) -> "caches.BaseCache | AbstractContextManager[None]":
    """
    Manages the active cache for Fleche.

    If ``new_cache`` is ``None``, returns the currently active cache.

    Otherwise, immediately sets ``new_cache`` as the active cache and returns a context manager.
    When used in a ``with`` statement the previous cache is restored on exit; when the returned
    context manager is discarded the new cache remains active (sticky behaviour).

    Args:
        new_cache: Cache object or named cache string to activate, or ``None`` to query.
        stack: If ``True``, wrap ``new_cache`` in a :class:`.CacheStack` on top of the current cache.

    Returns:
        The current :class:`.BaseCache` when called without arguments, otherwise a
        :class:`._StickyContext` context manager.
    """
    if new_cache is None:
        return _CACHE.get()

    if isinstance(new_cache, str):
        new_cache = config.load_cache_config(new_cache)
    if not isinstance(new_cache, caches.BaseCache):
        raise ValueError(new_cache)

    if stack:
        new_cache = _CACHE.get().push(new_cache)

    token = _CACHE.set(new_cache)
    return _StickyContext(_CACHE, token)


_METADATA: ContextVar[tuple[metadata.MetaData, ...]] = ContextVar(
    "fleche.METADATA", default=config.load_default_metadata()
)


def meta(
    *new_metadata: metadata.MetaData, stack=False
) -> AbstractContextManager[None]:
    """
    Manages the active metadata for Fleche.

    Immediately sets ``new_metadata`` as the active metadata and returns a context manager.
    When used in a ``with`` statement the previous metadata is restored on exit; when the
    returned context manager is discarded the new metadata remains active (sticky behaviour).

    Args:
        *new_metadata: :class:`.MetaData` instances to activate.
        stack: If ``True``, prepend the current metadata tuple before the new entries.

    Returns:
        A :class:`._StickyContext` context manager.
    """
    new_metadata = tuple(new_metadata)
    if stack:
        new_metadata = _METADATA.get() + new_metadata

    token = _METADATA.set(new_metadata)
    return _StickyContext(_METADATA, token)


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

    @property
    def fleche(self):
        """Return a .fleche namespace whose helpers run in the bound cache/meta context."""
        ns = self.func.fleche  # ty: ignore[unresolved-attribute]
        return SimpleNamespace(**{
            name: BoundWrapper(helper, self.cache, self.meta)
            for name, helper in vars(ns).items()
        })

    def __call__(self, *args, **kwargs):
        def _call():
            _CACHE.set(self.cache)
            _METADATA.set(self.meta)
            return self.func(*args, **kwargs)
        return contextvars.copy_context().run(_call)
