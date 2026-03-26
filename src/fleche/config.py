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
from typing import Any

from . import storage, metadata
from .caches import Cache

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


def _get_storage(config: dict[str, Any]) -> storage.Storage:
    storage_type = config.pop("type")
    match storage_type:
        case "Memory":
            return storage.Memory({})
        case "Void":
            return storage.Void()
        case "DestructuringStorage":
            inner = _get_storage(config.pop("storage"))
            return storage.DestructuringStorage(inner)
        case "PickleFile":
            return storage.PickleFile.with_pickle(**config)
        case "CloudpickleFile":
            return storage.PickleFile.with_cloudpickle(**config)
        case "DillFile":
            return storage.PickleFile.with_dill(**config)
        case "BagOfHoldingH5File" | "Sql":
            return getattr(storage, storage_type)(**config)
        case _:
            raise ValueError(f"Unknown storage type: {storage_type}")


def storage_to_config(s: storage.Storage) -> dict[str, Any]:
    """Convert a Storage instance to a config dict (inverse of ``_get_storage``).

    The returned dict contains a ``"type"`` key and any additional parameters
    needed to reconstruct the storage via :func:`_get_storage`.
    :class:`~fleche.storage.DestructuringStorage` is handled as a first-class
    case, producing a nested ``"storage"`` entry for its inner backend.
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
