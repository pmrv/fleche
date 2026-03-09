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
from pathlib import Path
import os
from typing import Any

from . import storage, metadata
from .caches import Cache

logger = logging.getLogger("fleche.config")

_live_caches: dict[str, Cache] = {}


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

    with open(path, "rb") as f:
        config = tomllib.load(f)

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

    with open(path, "rb") as f:
        config = tomllib.load(f)

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
        cache_config = config[cache_name]

    cache = _create_cache(cache_config)
    _live_caches[cache_name] = cache
    return cache
