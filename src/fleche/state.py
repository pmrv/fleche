import contextvars
from contextlib import AbstractContextManager
from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from functools import partial
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


def _reconstruct_bound_wrapper(func, bound_cache, bound_meta):
    """Module-level factory used by BoundWrapper.__reduce__ (contextvars.Context is not picklable)."""
    def _setup():
        _CACHE.set(bound_cache)
        _METADATA.set(bound_meta)
    ctx = contextvars.copy_context()
    ctx.run(_setup)
    return BoundWrapper(func, bound_cache, bound_meta, ctx)


@dataclass(frozen=True, eq=True)
class BoundWrapper:
    """Utility class that freezes global state for the cache and metadata config.

    Essentially acts like an early binding closure.

    This is intended to enable passing around fleche-decorated functions in pickled form by baking in the state into the
    pickle on request."""

    func: Callable
    cache: caches.BaseCache
    meta: tuple[metadata.MetaData, ...]
    ctx: contextvars.Context = field(compare=False, repr=False)

    @classmethod
    def bind(cls, func):
        """Bind cache and metadata state.

        Returns a new callable that will behave always as if run under the context under which :meth:`.bind()` was
        originally called.

        Args:
            func (callable): any callable; plain functions that only call fleche-wrapped ones are explicitly allowed

        Returns:
            :class:`.BoundWrapper`: instance with the bound cache and metadata state"""
        return cls(func, _CACHE.get(), _METADATA.get(), contextvars.copy_context())

    @property
    def fleche(self):
        """Return a .fleche namespace whose helpers run in the bound cache/meta context.

        Also handles method-bound wrappers where ``self.func`` is ``partial(wrapper, obj, ...)``:
        unwraps the partial chain to find the underlying fleche namespace and pre-applies the
        captured positional/keyword prefix to each helper.
        """
        func = self.func
        positional_prefix: tuple = ()
        keyword_prefix: dict = {}
        while isinstance(func, partial):
            positional_prefix = func.args + positional_prefix
            keyword_prefix = {**keyword_prefix, **func.keywords}
            func = func.func

        if not hasattr(func, 'fleche'):
            raise AttributeError(
                f"BoundWrapper.fleche requires a fleche-decorated function; "
                f"{self.func!r} has no .fleche namespace"
            )

        ns = func.fleche

        def _bind_helpers():
            result = {}
            for name in vars(ns):
                helper = getattr(ns, name)
                if positional_prefix or keyword_prefix:
                    helper = partial(helper, *positional_prefix, **keyword_prefix)
                result[name] = BoundWrapper.bind(helper)
            return result

        return SimpleNamespace(**self.ctx.run(_bind_helpers))

    def __call__(self, *args, **kwargs):
        return self.ctx.run(self.func, *args, **kwargs)

    def __reduce__(self):
        return (_reconstruct_bound_wrapper, (self.func, self.cache, self.meta))
