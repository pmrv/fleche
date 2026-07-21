from contextlib import AbstractContextManager
from contextvars import ContextVar, Token
from dataclasses import dataclass
from typing import Any, overload, Callable

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
    new_cache: "caches.BaseCache | str | dict[str, Any] | list[dict[str, Any]]",
    stack: bool = False,
) -> AbstractContextManager[None]: ...


def cache(
    new_cache: "caches.BaseCache | str | dict[str, Any] | list[dict[str, Any]] | None" = None,
    stack: bool = False,
) -> "caches.BaseCache | AbstractContextManager[None]":
    """
    Manages the active cache for Fleche.

    If ``new_cache`` is ``None``, returns the currently active cache.

    Otherwise, immediately sets ``new_cache`` as the active cache and returns a context manager.
    When used in a ``with`` statement the previous cache is restored on exit; when the returned
    context manager is discarded the new cache remains active (sticky behaviour).

    Args:
        new_cache: Cache object, named cache string, or config to activate, or
            ``None`` to query.  The strings ``'memory'`` and ``'void'`` return
            transient backends regardless of configuration.  The string
            ``'default'`` activates whichever cache the config file designates
            as the default — note that this is **not** the same as passing
            ``None``, which returns the *currently active* cache without
            changing anything.  A ``dict`` or ``list`` is passed straight to
            :func:`~fleche.config.cache_from_config`, so an ad-hoc cache can be
            built inline, e.g. ``cache({"template": "pickle", "root": ".cache"})``.
        stack: If ``True``, wrap ``new_cache`` in a :class:`.CacheStack` on top of the current cache.

    Returns:
        The current :class:`.BaseCache` when called without arguments, otherwise a
        :class:`._StickyContext` context manager.
    """
    if new_cache is None:
        return _CACHE.get()

    if isinstance(new_cache, caches.BaseCache):
        resolved = new_cache
    elif isinstance(new_cache, str):
        resolved = config.load_cache_config(new_cache)
    elif isinstance(new_cache, (dict, list)):
        resolved = config.cache_from_config(new_cache)
    else:
        raise ValueError(new_cache)

    if stack:
        resolved = _CACHE.get().push(resolved)

    token = _CACHE.set(resolved)
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
    """A plain callable that freezes cache and metadata state at construction time.

    :class:`.BoundWrapper` is intentionally a minimal wrapper: it captures the active
    :class:`.BaseCache` and metadata tuple and restores them around every call to the
    wrapped function, but it does **not** expose the ``fleche`` helper namespace
    (``digest``, ``call``, ``load``, ``contains``, ``query``, ``rerun``).  Those
    helpers are available on the original decorated function.

    This is intended to enable passing around fleche-decorated functions in pickled
    form by baking the active state into the object."""

    func: Callable
    cache: caches.BaseCache
    meta: tuple[metadata.MetaData, ...]

    @classmethod
    def bind(cls, func):
        """Bind cache and metadata state.

        Returns a plain callable that always executes as if called under the context
        in which :meth:`.bind()` was originally invoked.  The returned object is a
        :class:`.BoundWrapper` — a simple dataclass with a ``__call__`` method — and
        does **not** carry the ``fleche`` helper namespace.  To access helpers such as
        ``digest`` or ``query``, use them on the original decorated function.

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
