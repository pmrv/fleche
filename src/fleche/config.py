"""
Configuration system for fleche.

Example cache.toml:

[default]
cache = "mycache"
metadata = ["Runtime", "CallInfo"]

[mycache]
values.type = "Memory"
calls.type = "Memory"

[transient]
values.type = "CloudpickleFile"
values.root = ".fleche/values"
calls.type = "CloudpickleFile"
calls.root = ".fleche/calls"

[global]
values.type = "BagOfHoldingH5File"
values.root = "~/.fleche/values"
calls.type = "CloudpickleFile"
calls.root = "~/.fleche/calls"

"""

import tomllib
import logging
from typing import Literal, cast, overload
from pathlib import Path
import os
from typing import Any

from . import storage, metadata
from .caches import BaseCache, Cache, CacheStack, ReadOnlyCache, SizeLimitedCache

logger = logging.getLogger("fleche.config")

_live_caches: dict[str, Cache] = {}


def _load_config(path: Path) -> dict[str, Any]:
    try:
        with open(path, "rb") as f:
            return tomllib.load(f)
    except Exception as e:
        logger.error("Failed to load configuration from %s: %s", path, e)
        return {}


def _get_config_path() -> Path | None:
    path = Path("fleche.toml")
    if path.exists():
        return path.absolute()
    logger.info("Local config %s does not exist, trying global", path)

    if "XDG_CONFIG_HOME" in os.environ:
        path = Path(os.environ["XDG_CONFIG_HOME"]) / "fleche" / "cache.toml"
    elif "HOME" in os.environ:
        path = Path(os.environ["HOME"]) / ".fleche.toml"
    else:
        path = Path("~").expanduser() / ".fleche.toml"

    if path.exists():
        return path
    logger.info("Global config %s does not exist", path)


def load_default_metadata():
    """
    Load the default metadata from the configuration file.
    """
    path = _get_config_path()
    if path is None or not path.exists():
        return (metadata.Runtime(),)

    config = _load_config(path)

    if "default" not in config or "metadata" not in config["default"]:
        return (metadata.Runtime(),)

    meta_names = config["default"]["metadata"]

    meta_objects = []
    for name in meta_names:
        if name == "Tags":
            raise ValueError("Tags metadata cannot be configured from the config file.")
        elif name == "Runtime":
            meta_objects.append(metadata.Runtime())
        else:
            raise ValueError(f"Unknown metadata type in config: {name}")

    return tuple(meta_objects)

_STORAGE_NAME_MAPPING = {
        ("memory", "value"): storage.ValueMemory,
        ("memory", "call"): storage.CallMemory,
        ("void", "value"): storage.ValueVoid,
        ("void", "call"): storage.CallVoid,
        ("bagofholding_hdf", "value"): storage.ValueBagOfHoldingH5File,
        ("bagofholding_hdf", "call"): storage.CallBagOfHoldingH5File,
        ("pickle", "value"): storage.ValuePickleFile.with_pickle,
        ("pickle", "call"): storage.CallPickleFile.with_pickle,
        ("dill", "value"): storage.ValuePickleFile.with_dill,
        ("dill", "call"): storage.CallPickleFile.with_dill,
        ("cloudpickle", "value"): storage.ValuePickleFile.with_cloudpickle,
        ("cloudpickle", "call"): storage.CallPickleFile.with_cloudpickle,
}

_STORAGE_CLASS_TO_NAME: dict[type, str] = {
    storage.ValueMemory: "memory",
    storage.CallMemory: "memory",
    storage.ValueVoid: "void",
    storage.CallVoid: "void",
    storage.ValueBagOfHoldingH5File: "bagofholding_hdf",
    storage.CallBagOfHoldingH5File: "bagofholding_hdf",
    storage.ValuePickleFile: "pickle",   # serializer determines the actual name
    storage.CallPickleFile: "pickle",
}


@overload
def storage_from_config(d: dict[str, Any], type="call") -> storage.CallStorage: ...

@overload
def storage_from_config(d: dict[str, Any], type="value") -> storage.ValueStorage: ...

def storage_from_config(d: dict[str, Any], type: Literal["call", "value"]) -> storage.ValueStorage | storage.CallStorage:
    """Construct a :class:`~fleche.storage.StorageBackend` from a config dict.

    The dict must contain a ``"type"`` key (case-sensitive) and any additional
    parameters required by that storage backend.  The input dict is **not**
    mutated.
    """
    d = dict(d)
    backend = d.pop("type")
    match backend:
        case "memory":
            return _STORAGE_NAME_MAPPING[backend, type]({})
        case "void":
            return _STORAGE_NAME_MAPPING[backend, type]()
        case "bagofholding_hdf" | "pickle" | "dill" | "cloudpickle":
            return _STORAGE_NAME_MAPPING[backend, type](**d)
        case "sql" if type == "call":
            return storage.Sql(**d)
        case _:
            raise ValueError(f"Unknown storage type '{backend}' for {type} storage!")


def storage_to_config(s: storage.ValueStorage | storage.CallStorage) -> dict[str, Any]:
    """Convert a Storage instance to a config dict (inverse of ``storage_from_config``).

    The returned dict contains a ``"type"`` key and any additional parameters
    needed to reconstruct the storage via :func:`storage_from_config`.
    """
    import types

    cls = type(s)
    if cls not in _STORAGE_CLASS_TO_NAME and not isinstance(s, storage.Sql):
        raise ValueError(f"Cannot convert storage of type {cls.__name__!r} to config")

    if isinstance(s, (storage.ValueMemory, storage.CallMemory)):
        return {"type": "memory"}
    elif isinstance(s, (storage.ValueVoid, storage.CallVoid)):
        return {"type": "void"}
    elif isinstance(s, (storage.ValuePickleFile, storage.CallPickleFile)):
        serializer = s.serializer
        serializer_name = serializer.__name__ if isinstance(serializer, types.ModuleType) else str(serializer)
        match serializer_name:
            case "pickle":
                type_name = "pickle"
            case "cloudpickle":
                type_name = "cloudpickle"
            case "dill":
                type_name = "dill"
            case _:
                raise ValueError(f"Unknown PickleFile serializer: {serializer_name!r}")
        return {"type": type_name, "root": str(s.root)}
    elif isinstance(s, (storage.ValueBagOfHoldingH5File, storage.CallBagOfHoldingH5File)):
        return {"type": "bagofholding_hdf", "root": str(s.root)}
    elif isinstance(s, storage.Sql):
        return {"type": "sql", "url": s.url}
    else:
        raise ValueError(f"Cannot convert storage of type {cls.__name__!r} to config")


def cache_from_config(d: "dict[str, Any] | list[dict[str, Any]]") -> BaseCache:
    """Construct a :class:`~fleche.caches.BaseCache` from a config dict or list.

    The cache type is determined **implicitly** from the shape of the input:

    - A **list** of dicts is treated as a :class:`~fleche.caches.CacheStack`,
      with each element processed recursively.
    - A **dict** containing a ``max_size`` key creates a
      :class:`~fleche.caches.SizeLimitedCache`.
    - A **dict** containing ``read_only: true`` wraps the resulting cache in a
      :class:`~fleche.caches.ReadOnlyCache`.
    - Otherwise a plain :class:`~fleche.caches.Cache` is created.

    The input dict is **not** mutated.

    Examples::

        # Plain cache with in-memory storage
        cache_from_config({
            "values": {"type": "memory"},
            "calls": {"type": "memory"},
        })

        # Size-limited cache — presence of max_size selects SizeLimitedCache
        cache_from_config({
            "values": {"type": "memory"},
            "calls": {"type": "memory"},
            "max_size": 100,
        })

        # Read-only cache — read_only: true wraps the cache in ReadOnlyCache
        cache_from_config({
            "values": {"type": "memory"},
            "calls": {"type": "memory"},
            "read_only": True,
        })

        # CacheStack — a list of dicts is implicitly treated as a stack
        cache_from_config([
            {"values": {"type": "memory"}, "calls": {"type": "memory"}},
            {"values": {"type": "void"}, "calls": {"type": "void"}},
        ])
    """
    if isinstance(d, list):
        return CacheStack(tuple(cache_from_config(c) for c in d))

    d = dict(d)
    read_only = d.pop("read_only", False)
    max_size = d.pop("max_size", None)

    values_storage = storage_from_config(d["values"], "value")
    calls_storage = storage_from_config(d["calls"], "call")

    if max_size is not None:
        cache: BaseCache = SizeLimitedCache(values=values_storage, calls=calls_storage, max_size=max_size)
    else:
        cache = Cache(values=values_storage, calls=calls_storage)

    if read_only:
        cache = ReadOnlyCache(cache)

    return cache


def cache_to_config(c: BaseCache) -> "dict[str, Any] | list[dict[str, Any]]":
    """Convert a :class:`~fleche.caches.BaseCache` to a config dict or list.

    This is the inverse of :func:`cache_from_config`.  The output can be
    round-tripped back via ``cache_from_config(cache_to_config(cache))``.

    - :class:`~fleche.caches.Cache` → dict with ``"values"`` and ``"calls"``
    - :class:`~fleche.caches.SizeLimitedCache` → same dict plus ``"max_size"``
    - :class:`~fleche.caches.ReadOnlyCache` wrapping a ``Cache`` or
      ``SizeLimitedCache`` → inner cache dict with ``"read_only": True``
    - :class:`~fleche.caches.CacheStack` → list of dicts

    Raises:
        ValueError: for unsupported cache types or unsupported
            ``ReadOnlyCache`` inner types.
    """
    match c:
        case SizeLimitedCache():
            return {
                "values": storage_to_config(c.values),
                "calls": storage_to_config(c.calls),
                "max_size": c.max_size,
            }
        case Cache():
            return {
                "values": storage_to_config(c.values),
                "calls": storage_to_config(c.calls),
            }
        case ReadOnlyCache():
            inner = c.cache
            if not isinstance(inner, (Cache, SizeLimitedCache)):
                raise ValueError(
                    f"ReadOnlyCache wrapping {type(inner).__name__!r} cannot be serialised to config"
                )
            d = cache_to_config(inner)
            assert isinstance(d, dict)
            d["read_only"] = True
            return d
        case CacheStack():
            return cast("list[dict[str, Any]]", [cache_to_config(s) for s in c.stack])
        case _:
            raise ValueError(f"Cannot convert cache of type {type(c).__name__!r} to config")


def _create_cache(cache_config: dict[str, Any]) -> Cache:
    values = storage_from_config(cache_config["values"], "value")
    calls = storage_from_config(cache_config["calls"], "call")
    return Cache(values=values, calls=calls)


def load_cache_config(name: str | None = None) -> Cache:
    """
    Load a cache from the configuration file.

    If name is None, the default cache is loaded.
    The names 'memory' and 'void' are special-cased to return a transient
    in-memory cache and a no-op cache respectively.

    Note: The `Tags` metadata cannot be configured from the config file.
    """
    if name in _live_caches:
        return _live_caches[name]

    if name == "memory":
        cache = Cache(storage.ValueMemory({}), storage.CallMemory({}))
        _live_caches[name] = cache
        return cache

    if name == "void":
        cache = Cache(storage.ValueVoid(), storage.CallVoid())
        _live_caches[name] = cache
        return cache

    path = _get_config_path()
    if path is None or not path.exists():
        if name is not None:
            logger.warning(
                "No config file found. Using default memory cache for '%s'.", name
            )
        else:
            logger.warning("No config file found. Using default memory cache.")
        return Cache(storage.ValueMemory({}), storage.CallMemory({}))

    config = _load_config(path)

    cache_name = name
    cache_config = None

    if cache_name is None:
        if "default" not in config or "cache" not in config["default"]:
            logger.warning("No default cache configured. Using default memory cache.")
            return Cache(storage.ValueMemory({}), storage.CallMemory({}))

        default_cache = config["default"]["cache"]
        if isinstance(default_cache, str):
            return load_cache_config(default_cache)
        else:
            cache_name = "default"
            cache_config = default_cache

    if cache_config is None:
        if cache_name not in config:
            logger.warning(
                "Cache '%s' not found in configuration. Using default memory cache.",
                cache_name,
            )
            return Cache(storage.ValueMemory({}), storage.CallMemory({}))
        cache_config = config[cache_name]

    cache = _create_cache(cache_config)
    _live_caches[cache_name] = cache
    return cache
