import os
from pathlib import Path
from functools import wraps, partial
from types import SimpleNamespace
from typing import Any, Callable, Dict, Iterable, TypeVar
from dataclasses import dataclass, replace
import tempfile
import contextlib
from collections import defaultdict
from concurrent.futures import Future

from . import digest
from . import state
from . import metadata
from .call import Call, AnyCall, FunctionProfile, Ignored, QueryCall, Required, bind, _get_profile
from .caches import Rejected, BaseCache, RefreshingCache


import logging

# make messages from decorator below appear as if from the main module
logger = logging.getLogger("fleche")


def _as_tuple(x: None | str | Iterable[str]) -> tuple[str, ...]:
    if x is None:
        return ()
    if isinstance(x, str):
        return (x,)
    return tuple(x)


def process_ignore_required_args(
        func,
        ignore: None | str | Iterable[str] = None,
        require: None | str | Iterable[str] = None,
) -> FunctionProfile:
    """Merges explicit ignore/require decorator args into the function profile (annotation-based markers already in profile)."""
    profile = _get_profile(func)
    extra_ignored = frozenset(_as_tuple(ignore))
    extra_required = frozenset(_as_tuple(require))
    if not extra_ignored and not extra_required:
        return profile
    return replace(profile,
                   ignored=profile.ignored | extra_ignored,
                   required=profile.required | extra_required)


def _get_working_directory_root() -> Path:
    """
    Determines the root directory for fleche working directories, following the XDG spec.
    """
    xdg_cache_home = os.environ.get("XDG_CACHE_HOME") or (Path.home() / ".cache")
    root = Path(xdg_cache_home) / "fleche" / "cwd"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _attach(wrapper, fn, *, name, doc_prefix, ret=None, extra_doc=""):
    fn.__name__ = name
    fn.__qualname__ = f"{wrapper.__qualname__}.{name}"
    _doc = f"{doc_prefix} {wrapper.__name__}."
    if extra_doc:
        _doc += f"\n\n{extra_doc}"
    _doc += f"\n\n{wrapper.__doc__ or ''}"
    fn.__doc__ = _doc
    fn.__annotations__ = dict(fn.__annotations__)
    if ret is not None:
        fn.__annotations__["return"] = ret
    setattr(wrapper, name, fn)
    setattr(wrapper.fleche, name, fn)


_T = TypeVar("_T")


_QUERY_DOC = """Return matching results from current cache.

See :class:`CallStorage.query' for details, except that calls returned from here will have their arguments
and results restored from the value storage via :class:`Cache.query`.

Args:
    *args, **kwargs: function arguments that should be matched in returned calls; pass `None` as a wildcard
    metadata (dict[str, dict[str, json]]): metadata tags to additionall filter on; if this shadows a
        function kwargs of the same name, you must pass it by position instead.

Returns:
    iterable of matching :class:`.Call`
"""


@dataclass(frozen=True)
class _HelperSpec:
    """Spec for a helper function attached to a fleche-decorated function."""
    name: str
    doc_prefix: str
    builder: Any  # Callable[[_HelpersCtx], Callable]
    ret: Any = None
    extra_doc: str = ""
    ctx_attr: str | None = None


class _HelpersCtx:
    """Mutable context accumulated while building helpers for a fleche-decorated function."""
    __slots__ = ('func', 'policy', 'meta', 'isolate', 'hash_version', 'hash_module', 'hash_code',
                 'get_call', 'digest_func', 'wrapper')

    def __init__(self, func, policy, meta, isolate, hash_version, hash_module, hash_code):
        self.func = func
        self.policy = policy
        self.meta = meta
        self.isolate = isolate
        self.hash_version = hash_version
        self.hash_module = hash_module
        self.hash_code = hash_code
        self.get_call = None
        self.digest_func = None
        self.wrapper = None


def make_get_call(func, policy, hash_version, hash_module, hash_code):
    """Build the `.call` helper that produces a :class:`.Call` for the given arguments."""
    @wraps(func)
    def get_call(*args, **kwargs):
        call = Call.from_call(func, *args, **kwargs)
        # drop ignored arguments for the saved call object to make our lives much simpler when hashing or saving it
        # if we leave them in, then Cache.save needs to know about them indirectly to ensure correct digest key
        # generation, but then we'd also have to save it somehow and that just seems bothersome in particular for
        # Sql Callstorage.  We could add a new table there connecting unique functions and their ignored args, but
        # meh.
        policy.strip_for_key(call.arguments)
        if not hash_version:
            call.version = None
        if not hash_module:
            call.module = None
        if not hash_code:
            call.code_digest = None
        return call
    return get_call


def make_query(func, policy):
    """Build the `.query` helper that yields matching calls from the active cache."""
    def _query_func(
        *args, metadata={}, **kwargs
    ) -> Iterable[AnyCall]:
        call = QueryCall.from_call(func, *args, **kwargs)
        policy.strip_for_key(call.arguments)
        if "metadata" in call.arguments:
            logger.warning(
                "Function argument 'metadata' shadowed by query argument"
            )
        call.metadata = metadata
        return state._CACHE.get().query(call)

    wraps(func)(_query_func)
    return _query_func


def make_rerun(func, wrapper):
    """Build the `.rerun` helper that forces recursive reevaluation through a :class:`RefreshingCache`."""
    @wraps(func)
    def _rerun_func(*args, **kwargs):
        cache: BaseCache = state._CACHE.get()
        with state.cache(RefreshingCache(cache)):
            return wrapper(*args, **kwargs)
    return _rerun_func


def make_wrapper(func, policy, meta, isolate, get_call):
    """Build the cached wrapper returned by :func:`fleche`."""
    @wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> _T:
        cache: BaseCache = state._CACHE.get()

        # expand args passed as digest early so that everything else below sees the real values
        args = tuple(
            cache.load_value(arg) if isinstance(arg, digest.Digest) else arg
            for arg in args
        )
        kwargs = {
            k: (cache.load_value(v) if isinstance(v, digest.Digest) else v)
            for k, v in kwargs.items()
        }

        try:
            call = get_call(*args, **kwargs)
            key = call.to_lookup_key()
        except digest.Unhashable as e:
            logger.warning("No hash for argument: %s", e.args[0])
            return func(*args, **kwargs)

        missing = policy.check_required(args, kwargs)
        if missing:
            logger.warning(
                "Missing required keyword arguments for caching: %s", missing
            )
            return func(*args, **kwargs)

        try:
            result = cache.load(key).result
            logger.debug("Cache hit for %s with key %s", call.name, key)
            return result
        except KeyError:
            logger.debug("Cache miss for %s with key %s", call.name, key)

        def _run_and_cache():
            active_meta = state._METADATA.get() + tuple(meta)
            metadata: Dict[str, Any] = defaultdict(dict)
            for m in active_meta:
                metadata[m.name] |= m.pre(replace(call, metadata={}))

            result: _T = func(*args, **kwargs)

            def _cache(future = None):
                if future is None:
                    call.result = result
                else:
                    call.result = future.result()
                if call.result is None:
                    logger.warning("Function returned None, not caching")
                    return None
                for m in active_meta:
                    metadata[m.name] |= m.post(
                        metadata[m.name], replace(call, metadata={})
                    )
                try:
                    call.metadata = metadata
                    logger.debug("Saving result for %s with key %s", call.name, key)
                    cache.save(call)
                except Rejected as e:
                    logger.warning("Cache rejected save: %s", e.args)
                return call.result

            if not isinstance(result, Future):
                return _cache()
            else:
                result.add_done_callback(_cache)
                return result

        if isolate:
            root = _get_working_directory_root()
            # Create a unique working directory to avoid race conditions during concurrent execution.
            # NOTE: os.chdir is process-wide and not thread-safe.
            with tempfile.TemporaryDirectory(dir=root, prefix=f"{key}_") as workdir:
                with contextlib.chdir(workdir):
                    return _run_and_cache()
        else:
            return _run_and_cache()
    return wrapper


# Specs for helpers built before make_wrapper (may seed ctx.get_call / ctx.digest_func).
_PRE_WRAPPER_SPECS: list[_HelperSpec] = [
    _HelperSpec(
        name="call",
        doc_prefix="Get the Call object for",
        ret=Call,
        ctx_attr="get_call",
        builder=lambda ctx: make_get_call(
            ctx.func, ctx.policy, ctx.hash_version, ctx.hash_module, ctx.hash_code
        ),
    ),
    _HelperSpec(
        name="digest",
        doc_prefix="Get the cache key for",
        ret=digest.Digest,
        ctx_attr="digest_func",
        builder=lambda ctx: wraps(ctx.func)(
            lambda *a, **kw: ctx.get_call(*a, **kw).to_lookup_key()
        ),
    ),
    _HelperSpec(
        name="query",
        doc_prefix="Return matching results from current cache for",
        ret=Iterable[Call],
        extra_doc=_QUERY_DOC,
        builder=lambda ctx: make_query(ctx.func, ctx.policy),
    ),
    _HelperSpec(
        name="load",
        doc_prefix="Load result from cache for",
        builder=lambda ctx: wraps(ctx.func)(
            lambda *a, **kw: state._CACHE.get().load(ctx.digest_func(*a, **kw)).result
        ),
    ),
    _HelperSpec(
        name="contains",
        doc_prefix="Check if result is in cache for",
        ret=bool,
        builder=lambda ctx: wraps(ctx.func)(
            lambda *a, **kw: state._CACHE.get().contains(ctx.digest_func(*a, **kw))
        ),
    ),
]

# Specs for helpers that need ctx.wrapper (built after make_wrapper).
_POST_WRAPPER_SPECS: list[_HelperSpec] = [
    _HelperSpec(
        name="rerun",
        doc_prefix="Force reevaluation recursively for",
        builder=lambda ctx: make_rerun(ctx.func, ctx.wrapper),
    ),
    _HelperSpec(
        name="bind",
        doc_prefix="Create a BoundWrapper for",
        ret=state.BoundWrapper,
        builder=lambda ctx: (
            lambda *a, **kw: state.BoundWrapper.bind(
                partial(ctx.wrapper, *a, **kw) if (a or kw) else ctx.wrapper
            )
        ),
    ),
]


def fleche(
    _func=None,
    *,
    version: str | int | None = None,
    meta: tuple[metadata.MetaData, ...] = (),
    hash_version: bool = True,
    hash_module: bool = True,
    hash_code: bool = False,
    require: None | str | list[str] | tuple[str] = None,
    ignore: None | str | list[str] | tuple[str] = None,
    isolate: bool = False,
):
    """
    Cache decorator for functions.

    The decorated function is enhanced with helper methods, accessible either directly
    on the wrapped function or bundled under a ``.fleche`` :class:`types.SimpleNamespace`
    (e.g. ``f.fleche.call(...)`` is equivalent to ``f.call(...)``):

    - .call(*args, **kwargs): Get the :class:`.Call` object.
    - .digest(*args, **kwargs): Get the cache key.
    - .load(*args, **kwargs): Load result from cache.
    - .contains(*args, **kwargs): Check if result is in cache.
    - .query(*args, **kwargs): Return matching calls from the active cache.
    - .rerun(*args, **kwargs): Forces reevaluation recursively.
    - .bind(*args, **kwargs): Create a :class:`.BoundWrapper` that freezes the current cache/metadata state.
      Optionally pre-applies *args*/*kwargs* via :func:`functools.partial`.
    The original function is available via .__wrapped__.

    .. warning::

        ``isolate=True`` is **not thread-safe**.  Internally it calls
        :func:`os.chdir`, which is a process-wide POSIX syscall shared by all
        threads.  Concurrent calls with ``isolate=True`` from multiple threads
        will clobber each other's working directory, and a thread may find its
        temporary directory deleted before it has finished using it.

        Use ``isolate=True`` only from a single thread, or run isolated calls
        in separate processes (e.g. via :class:`concurrent.futures.ProcessPoolExecutor`)
        where each process has its own working directory.
    """

    def decorator(func: Callable[..., _T]) -> Callable[..., _T]:
        """
        The actual decorator that wraps the function.
        """
        if version is not None:
            func.__version__ = version  # ty: ignore

        policy = process_ignore_required_args(func, ignore, require)
        ctx = _HelpersCtx(func, policy, meta, isolate, hash_version, hash_module, hash_code)

        helper_entries: list[tuple[_HelperSpec, Callable]] = []
        for spec in _PRE_WRAPPER_SPECS:
            fn = spec.builder(ctx)
            if spec.ctx_attr is not None:
                setattr(ctx, spec.ctx_attr, fn)
            helper_entries.append((spec, fn))

        ctx.wrapper = wrapper = make_wrapper(ctx.func, ctx.policy, ctx.meta, ctx.isolate, ctx.get_call)

        for spec in _POST_WRAPPER_SPECS:
            helper_entries.append((spec, spec.builder(ctx)))

        wrapper.fleche = SimpleNamespace()
        for spec, fn in helper_entries:
            _attach(wrapper, fn, name=spec.name, doc_prefix=spec.doc_prefix,
                    ret=spec.ret, extra_doc=spec.extra_doc)

        return wrapper

    if callable(_func):
        return decorator(_func)
    else:
        return decorator


__all__ = [
        "Ignored",
        "Required",
        "fleche",
]
