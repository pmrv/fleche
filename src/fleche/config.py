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
from pathlib import Path
import os
from typing import Any

from . import storage, metadata
from .cache import Cache

_live_caches: dict[str, Cache] = {}


def _get_config_path() -> Path | None:
    if "XDG_CONFIG_HOME" in os.environ:
        return Path(os.environ["XDG_CONFIG_HOME"]) / "fleche/cache.toml"
    elif "HOME" in os.environ:
        return Path(os.environ["HOME"]) / ".config/fleche/cache.toml"
    else:
        return None


def _get_storage(config: dict[str, Any]) -> storage.Storage:
    storage_type = config.pop("type")

    if storage_type == "Memory":
        return storage.Memory({})

    if "inner" in config:
        config["inner"] = _get_storage(config["inner"])

    cls = getattr(storage, storage_type)
    return cls(**config)


def load_default_metadata():
    """
    Load the default metadata from the configuration file.
    """
    path = _get_config_path()
    if path is None or not path.exists():
        return (metadata.Runtime(), metadata.CallInfo())

    with open(path, "rb") as f:
        config = tomllib.load(f)

    if "default" not in config or "metadata" not in config["default"]:
        return (metadata.Runtime(), metadata.CallInfo())

    meta_names = config["default"]["metadata"]

    meta_objects = []
    for name in meta_names:
        if name == "Tags":
            raise ValueError("Tags metadata cannot be configured from the config file.")
        else:
            meta_objects.append(getattr(metadata, name)())

    return tuple(meta_objects)


def _create_cache(cache_config: dict[str, Any]) -> Cache:
    values = _get_storage(cache_config["values"])
    calls = _get_storage(cache_config["calls"])
    return Cache(values=values, calls=calls)


def load_cache_config(name: str | None = None) -> Cache:
    """
    Load a cache from the configuration file.

    If name is None, the default cache is loaded.

    Note: The `Tags` metadata cannot be configured from the config file.
    """
    path = _get_config_path()
    if path is None or not path.exists():
        print("Warning: No config file found. Using default memory cache.")
        return Cache(storage.Memory({}), storage.Memory({}))

    with open(path, "rb") as f:
        config = tomllib.load(f)

    cache_name = name
    cache_config = None

    if cache_name is None:
        if "default" not in config or "cache" not in config["default"]:
            print("Warning: No default cache configured. Using default memory cache.")
            return Cache(storage.Memory({}), storage.Memory({}))

        default_cache = config["default"]["cache"]
        if isinstance(default_cache, str):
            cache_name = default_cache
        else:
            cache_name = "default"
            cache_config = default_cache

    if cache_name in _live_caches:
        return _live_caches[cache_name]

    if cache_config is None:
        cache_config = config[cache_name]

    cache = _create_cache(cache_config)
    _live_caches[cache_name] = cache
    return cache
