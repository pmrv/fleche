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
import types
from pathlib import Path
import os
from typing import Any, cast

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


def storage_from_config(d: dict[str, Any]) -> storage.Storage:
    """Construct a :class:`~fleche.storage.Storage` from a config dict.

    The dict must contain a ``"type"`` key (case-sensitive) and any additional
    parameters required by that storage backend.  The input dict is **not**
    mutated.

    Supported types: ``"Memory"``, ``"Void"``, ``"DestructuringStorage"``,
    ``"PickleFile"``, ``"CloudpickleFile"``, ``"DillFile"``,
    ``"BagOfHoldingH5File"``, ``"Sql"``.
    """
    d = dict(d)
    storage_type = d.pop("type")
    match storage_type:
        case "Memory":
            return storage.Memory({})
        case "Void":
            return storage.Void()
        case "DestructuringStorage":
            inner = storage_from_config(d.pop("storage"))
            return storage.DestructuringStorage(inner)
        case "PickleFile":
            return storage.PickleFile.with_pickle(**d)
        case "CloudpickleFile":
            return storage.PickleFile.with_cloudpickle(**d)
        case "DillFile":
            return storage.PickleFile.with_dill(**d)
        case "BagOfHoldingH5File" | "Sql":
            return getattr(storage, storage_type)(**d)
        case _:
            raise ValueError(f"Unknown storage type: {storage_type}")


def _get_storage(config: dict[str, Any]) -> storage.Storage:
    """Deprecated: use :func:`storage_from_config` instead."""
    return storage_from_config(config)


def storage_to_config(s: storage.Storage | storage.CallStorage) -> dict[str, Any]:
    """Convert a Storage or CallStorage instance to a config dict.

    The returned dict contains a ``"type"`` key and any additional parameters
    needed to reconstruct the storage via :func:`storage_from_config`.
    :class:`~fleche.storage.DestructuringStorage` is handled as a first-class
    case, producing a nested ``"storage"`` entry for its inner backend.

    Accepts both :class:`~fleche.storage.Storage` and bare
    :class:`~fleche.storage.CallStorage` instances (e.g. ``Sql``), since ``Sql``
    implements ``CallStorage`` directly without going through
    ``CallStorageAdapter``.
    """
    match s:
        case storage.DestructuringStorage(storage=inner):
            return {"type": "DestructuringStorage", "storage": storage_to_config(inner)}
        case storage.Memory():
            return {"type": "Memory"}
        case storage.Void():
            return {"type": "Void"}
        case storage.PickleFile():
            serializer = s.serializer
            serializer_name = serializer.__name__ if isinstance(serializer, types.ModuleType) else str(serializer)
            match serializer_name:
                case "pickle":
                    type_name = "PickleFile"
                case "cloudpickle":
                    type_name = "CloudpickleFile"
                case "dill":
                    type_name = "DillFile"
                case _:
                    raise ValueError(f"Unknown PickleFile serializer: {serializer_name!r}")
            return {"type": type_name, "root": str(s.root)}
        case storage.BagOfHoldingH5File():
            return {"type": "BagOfHoldingH5File", "root": str(s.root)}
        case storage.Sql():
            return {"type": "Sql", "url": s.url}
        case _:
            raise ValueError(f"Cannot convert storage of type {type(s).__name__!r} to config")


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

    The ``values`` storage is always wrapped in a
    :class:`~fleche.storage.DestructuringStorage` if it is not already one.
    The input dict is **not** mutated.

    Examples::

        # Plain cache with in-memory storage
        cache_from_config({
            "values": {"type": "Memory"},
            "calls": {"type": "Memory"},
        })

        # Size-limited cache — presence of max_size selects SizeLimitedCache
        cache_from_config({
            "values": {"type": "Memory"},
            "calls": {"type": "Memory"},
            "max_size": 100,
        })

        # Read-only cache — read_only: true wraps the cache in ReadOnlyCache
        cache_from_config({
            "values": {"type": "Memory"},
            "calls": {"type": "Memory"},
            "read_only": True,
        })

        # CacheStack — a list of dicts is implicitly treated as a stack
        cache_from_config([
            {"values": {"type": "Memory"}, "calls": {"type": "Memory"}},
            {"values": {"type": "Void"}, "calls": {"type": "Void"}},
        ])
    """
    if isinstance(d, list):
        return CacheStack(tuple(cache_from_config(c) for c in d))

    d = dict(d)
    read_only = d.pop("read_only", False)
    max_size = d.pop("max_size", None)

    values_storage = storage_from_config(d["values"])
    if not isinstance(values_storage, storage.DestructuringMixin):
        values_storage = storage.DestructuringStorage(values_storage)
    calls_storage = storage_from_config(d["calls"])

    if max_size is not None:
        cache: BaseCache = SizeLimitedCache(values=values_storage, _calls=calls_storage, max_size=max_size)
    else:
        cache = Cache(values=values_storage, _calls=calls_storage)

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

    ``values`` is serialised as-is (a ``DestructuringStorage`` wrapper is
    preserved in the output).  ``calls`` unwraps the
    :class:`~fleche.storage.CallStorageAdapter`.

    Raises:
        ValueError: for unsupported cache types or unsupported
            ``ReadOnlyCache`` inner types.
    """
    match c:
        case SizeLimitedCache():
            calls_storage = c.calls.storage if isinstance(c.calls, storage.CallStorageAdapter) else c.calls
            return {
                "values": storage_to_config(c.values),
                "calls": storage_to_config(calls_storage),
                "max_size": c.max_size,
            }
        case Cache():
            calls_storage = c.calls.storage if isinstance(c.calls, storage.CallStorageAdapter) else c.calls
            return {
                "values": storage_to_config(c.values),
                "calls": storage_to_config(calls_storage),
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
    values = _get_storage(cache_config["values"])
    calls = _get_storage(cache_config["calls"])
    return Cache(values=values, _calls=calls)


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
        cache = Cache(storage.Memory({}), storage.Memory({}))
        _live_caches[name] = cache
        return cache

    if name == "void":
        cache = Cache(storage.Void(), storage.Void())
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
        return Cache(storage.Memory({}), storage.Memory({}))

    config = _load_config(path)

    cache_name = name
    cache_config = None

    if cache_name is None:
        if "default" not in config or "cache" not in config["default"]:
            logger.warning("No default cache configured. Using default memory cache.")
            return Cache(storage.Memory({}), storage.Memory({}))

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
            return Cache(storage.Memory({}), storage.Memory({}))
        cache_config = config[cache_name]

    cache = _create_cache(cache_config)
    _live_caches[cache_name] = cache
    return cache
