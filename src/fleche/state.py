import pickle
from contextlib import AbstractContextManager, contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass
from typing import overload, Any, Callable, Iterator, TypeVar

from . import caches, config, metadata

_CACHE: ContextVar[caches.BaseCache] = ContextVar("fleche.CACHE")

#: Memoised fallbacks for the ContextVars below, keyed by ``"cache"``/``"metadata"``.
#: The config is only read the first time a value is actually needed, so importing
#: :mod:`fleche` does not touch the file system and tests can pick up a patched
#: config by clearing this dict.
_DEFAULTS: dict[str, Any] = {}

_T = TypeVar("_T")


def _lazy_default(var: ContextVar[_T], key: str, loader: Callable[[], _T]) -> _T:
    """Return ``var``'s active value, falling back to a memoised ``loader()`` result.

    The fallback is resolved on first use and cached in :data:`_DEFAULTS` under
    ``key``; clearing that entry (or the whole dict) forces re-resolution.
    """
    try:
        return var.get()
    except LookupError:
        if key not in _DEFAULTS:
            _DEFAULTS[key] = loader()
        return _DEFAULTS[key]


def get_cache() -> caches.BaseCache:
    """Return the active cache, falling back to the configured default.

    The default is resolved from the configuration files on first use and memoised
    in :data:`_DEFAULTS`.
    """
    return _lazy_default(_CACHE, "cache", config.load_cache_config)


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


def _sticky_set(var: ContextVar, value: object) -> _StickyContext:
    """Set *var* to *value* immediately and return a sticky context manager.

    Entering the returned context manager as a ``with``-block restores the previous
    value on exit; discarding it leaves *value* active.
    """
    return _StickyContext(var, var.set(value))


@contextmanager
def _hard_set(pairs: list[tuple[ContextVar, object]]) -> Iterator[None]:
    """Set every ``ContextVar`` in *pairs* immediately; reset in reverse order on exit.

    Unlike :func:`_sticky_set`, this is a hard scope: the values are always reset when
    the ``with``-block exits, regardless of how it exits.
    """
    tokens = [(var, var.set(value)) for var, value in pairs]
    try:
        yield
    finally:
        for var, token in reversed(tokens):
            var.reset(token)


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
            The strings ``'memory'`` and ``'void'`` return transient backends regardless of
            configuration.  The string ``'default'`` activates whichever cache the config
            file designates as the default — note that this is **not** the same as passing
            ``None``, which returns the *currently active* cache without changing anything.
            To activate a cache built from a config dict/list, construct it first with
            :meth:`~fleche.caches.BaseCache.from_config` and pass the result, e.g.
            ``cache(Cache.from_config({"template": "pickle", "root": ".cache"}))``.
        stack: If ``True``, wrap ``new_cache`` in a :class:`.CacheStack` on top of the current cache.

    Returns:
        The current :class:`.BaseCache` when called without arguments, otherwise a
        :class:`._StickyContext` context manager.
    """
    if new_cache is None:
        return get_cache()

    if isinstance(new_cache, str):
        new_cache = config.load_cache_config(new_cache)
    if not isinstance(new_cache, caches.BaseCache):
        raise ValueError(new_cache)

    if stack:
        new_cache = get_cache().push(new_cache)

    return _sticky_set(_CACHE, new_cache)


_METADATA: ContextVar[tuple[metadata.MetaData, ...]] = ContextVar("fleche.METADATA")


def get_metadata() -> tuple[metadata.MetaData, ...]:
    """Return the active metadata, falling back to the configured default.

    The default is resolved from the configuration files on first use and memoised
    in :data:`_DEFAULTS`.
    """
    return _lazy_default(_METADATA, "metadata", config.load_default_metadata)


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
        new_metadata = get_metadata() + new_metadata

    return _sticky_set(_METADATA, new_metadata)


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

    :class:`~fleche.state.BoundWrapper` is intentionally a minimal wrapper: it captures the active
    :class:`.BaseCache` and metadata tuple and restores them around every call to the
    wrapped function, but it does **not** expose the ``fleche`` helper namespace
    (``digest``, ``call``, ``load``, ``contains``, ``query``, ``rerun``).  Those
    helpers are available on the original decorated function.

    This is intended to enable passing around fleche-decorated functions in pickled
    form by baking the active state into the object."""

    func: Callable
    cache: caches.BaseCache
    meta: tuple[metadata.MetaData, ...]

    def __reduce__(self):
        # `func` is pickled into a standalone bytes payload up front, rather than
        # left for the outer pickler to serialise, so the choice of serialiser
        # does not depend on what is pickling the BoundWrapper. stdlib pickle can
        # only reference a function by (module, qualname); that fails for a
        # function that isn't importable that way (defined in __main__, a
        # notebook, or as a closure). stdlib ProcessPoolExecutor hardcodes
        # pickle and gives no hook to swap serialisers, so falling back to
        # cloudpickle only inside this payload — never for the BoundWrapper
        # itself — is what lets a by-value func survive a stdlib-pickle carrier.
        try:
            payload = pickle.dumps(self.func)
            by_value = False
        except Exception as e:
            try:
                import cloudpickle
            except ImportError:
                raise TypeError(
                    f"{self.func!r} is not importable by reference (e.g. it is "
                    "defined in __main__, a notebook, or a closure) and "
                    "'cloudpickle' is not installed to serialise it by value. "
                    "Install it with `pip install fleche[cloudpickle]`."
                ) from e
            payload = cloudpickle.dumps(self.func)
            by_value = True
        return (_unpickle_bound_wrapper, (by_value, payload, self.cache, self.meta))

    @classmethod
    def bind(cls, func):
        """Bind cache and metadata state.

        Returns a plain callable that always executes as if called under the context
        in which :meth:`.bind()` was originally invoked.  The returned object is a
        :class:`~fleche.state.BoundWrapper` — a simple dataclass with a ``__call__`` method — and
        does **not** carry the ``fleche`` helper namespace.  To access helpers such as
        ``digest`` or ``query``, use them on the original decorated function.

        Args:
            func (:class:`~collections.abc.Callable`): any callable; plain functions that only call fleche-wrapped ones are explicitly allowed

        Returns:
            :class:`~fleche.state.BoundWrapper`: instance with the bound cache and metadata state"""
        return cls(func, get_cache(), get_metadata())

    def __call__(self, *args, **kwargs):
        with _hard_set([(_CACHE, self.cache), (_METADATA, self.meta)]):
            return self.func(*args, **kwargs)


def _unpickle_bound_wrapper(by_value, payload, cache, meta):
    """Reconstruct a :class:`BoundWrapper` from :meth:`BoundWrapper.__reduce__`'s payload."""
    if by_value:
        import cloudpickle
        func = cloudpickle.loads(payload)
    else:
        func = pickle.loads(payload)
    return BoundWrapper(func, cache, meta)
