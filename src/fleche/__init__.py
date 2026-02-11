"""lru_cache on 'roids."""
import os
from dataclasses import replace
import shutil
import tempfile
import contextlib
from contextlib import contextmanager, AbstractContextManager
from contextvars import ContextVar
from collections import defaultdict
from functools import wraps
from pathlib import Path
from typing import Any, Callable, Dict, Optional, TypeVar, Union

from . import digest
from .invocation import Invocation
from .metadata import MetaData, PandasDB, Runtime, InvocationInfo, Tags
from .cache import Cache, Rejected
from . import storage

_T = TypeVar("_T")

_CACHE: ContextVar[Cache] = ContextVar(
    'fleche.CACHE',
    # default=Cache(storage.CloudpickleFile(Path(".fleche"))).metadb(PandasDB({}))
    default=Cache(storage.Memory({}), storage.Memory({})).metadb(PandasDB({}))
)


def cache(new_cache: Optional[Cache] = None, stack=False) -> Union[Cache, AbstractContextManager[None]]:
    """
    Manages the active cache for Fleche. If `new_cache` is provided, it returns a context manager
    that sets the cache for the duration of the context. If `new_cache` is None, it returns
    the currently active cache.

    Args:
        new_cache (Optional[Cache]): An optional Cache object to set as the active cache.
        stack (bool, default False): if True, construct a CacheStack, with new_cache at the bottom

    Returns:
        Union[Cache, Callable[..., Any]]: The current Cache object if `new_cache` is None,
                                       otherwise a context manager to set a new cache.
    """
    if new_cache is None:
        return _CACHE.get()

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


_METADATA: ContextVar[tuple[MetaData]] = ContextVar(
    "fleche.METADATA",
    # default=(Runtime(), Digest(), InvocationInfo())
    default=(Runtime(), InvocationInfo())
)


@contextmanager
def metadata(*new_metadata: MetaData, stack=False):
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
    return metadata(Tags(kwargs), stack=True)


def project(name):
    """A context manager to tag results with a project name.

    Args:
        name (str): The name of the project.
    """
    return tags(project=name)


def _get_working_directory_root() -> Path:
    """
    Determines the root directory for fleche working directories, following the XDG spec.
    """
    xdg_cache_home = os.environ.get('XDG_CACHE_HOME') or (Path.home() / '.cache')
    root = Path(xdg_cache_home) / 'fleche' / 'cwd'
    root.mkdir(parents=True, exist_ok=True)
    return root


def fleche(
    _func=None,
    *,
    version: int | None = None,
    meta: tuple[MetaData] = (),
    hash_version: bool = True,
    hash_module: bool = True,
    require: None | str | list[str] | tuple[str] = None,
    isolate: bool = False,
):

    def decorator(func: Callable[..., _T]) -> Callable[..., _T]:
        """
        The actual decorator that wraps the function.
        """
        if version is not None:
            func.__version__ = version

        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> _T:
            if require is None:
                required_args = ()
            elif isinstance(require, str):
                required_args = (require,)
            else:
                required_args = require
            if any(r not in kwargs for r in required_args):
                print(f"WARNING MISSING REQUIRED ARG: {required_args}")
                return func(*args, **kwargs)
            cache: Cache = _CACHE.get()
            try:
                inv = Invocation.from_call(func, *args, **kwargs)
                if not hash_version:
                    inv.version = None
                if not hash_module:
                    inv.module = None
                key: str = digest.digest(inv.to_lookup())
            except digest.Unhashable as e:
                print("WARNING NO HASH:", e.args[0])
                return func(*args, **kwargs)

            try:
                return cache.load(key).result
            except KeyError:
                pass

            def _run_and_cache():
                active_meta = _METADATA.get() + tuple(meta)
                metadata: Dict[str, Any] = defaultdict(dict)
                for m in active_meta:
                    metadata[m.name] |= m.pre(replace(inv, metadata={}))
                inv.result: _T = func(*args, **kwargs)
                if inv.result is None:
                    print("WARNING NO VALUE")
                    return None
                for m in active_meta:
                    metadata[m.name] |= m.post(metadata[m.name], replace(inv, metadata={}))
                try:
                    inv.metadata = metadata
                    cache.save(inv)
                except Rejected as e:
                    print("WARNING NO SAVE:", *e.args)
                return inv.result

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

    if callable(_func):
        return decorator(_func)
    else:
        return decorator
