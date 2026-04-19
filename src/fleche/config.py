"""
Configuration system for fleche.

Storage type names
------------------

The ``type`` key in a storage config dict is case-sensitive and uses the
following **lowercase** identifiers:

``"memory"``
    In-memory dict (:class:`~fleche.storage.ValueMemory` /
    :class:`~fleche.storage.CallMemory`).  No required keys.
    Optional (value backend): ``remaining_depth`` (int, default ``0``).

``"void"``
    No-op — discards all data (:class:`~fleche.storage.ValueVoid` /
    :class:`~fleche.storage.CallVoid`).  No required keys.
    Optional (value backend): ``remaining_depth`` (int, default ``0``).

``"pickle"``
    Filesystem backend serialised with the standard ``pickle`` module
    (:class:`~fleche.storage.ValuePickleFile` /
    :class:`~fleche.storage.CallPickleFile`).
    Required: ``root`` (path to storage directory).
    Optional: ``compress`` (bool, default ``False``) — gzip-compress files.
    Optional: ``lock_timeout`` (float, default ``1.0``) — write-lock wait timeout (s).
    Optional: ``lock_wait_start`` (float, default ``0.001``) — initial lock-poll
    interval for exponential backoff (s).
    Optional: ``secret_key`` (list of hex strings) — HMAC-SHA256 signing keys;
    each element is a hex-encoded byte string (same format as ``FLECHE_SECRET_KEY``).
    If omitted, falls back to the ``FLECHE_SECRET_KEY`` environment variable.
    Optional (value backend): ``remaining_depth`` (int, default ``0``).

``"cloudpickle"``
    Filesystem backend serialised with ``cloudpickle`` — handles more
    complex Python objects than ``pickle``.
    Required: ``root``.
    Optional: ``compress`` (bool, default ``False``) — gzip-compress files.
    Optional: ``lock_timeout`` (float, default ``1.0``) — write-lock wait timeout (s).
    Optional: ``lock_wait_start`` (float, default ``0.001``) — initial lock-poll
    interval for exponential backoff (s).
    Optional: ``secret_key`` (list of hex strings) — same as ``"pickle"``.
    Optional (value backend): ``remaining_depth`` (int, default ``0``).

``"dill"``
    Filesystem backend serialised with ``dill``.
    Required: ``root``.
    Optional: ``compress`` (bool, default ``False``) — gzip-compress files.
    Optional: ``lock_timeout`` (float, default ``1.0``) — write-lock wait timeout (s).
    Optional: ``lock_wait_start`` (float, default ``0.001``) — initial lock-poll
    interval for exponential backoff (s).
    Optional: ``secret_key`` (list of hex strings) — same as ``"pickle"``.
    Optional (value backend): ``remaining_depth`` (int, default ``0``).

``"bagofholding_hdf"``
    HDF5-backed storage via the ``bagofholding`` library
    (:class:`~fleche.storage.ValueBagOfHoldingH5File` /
    :class:`~fleche.storage.CallBagOfHoldingH5File`).
    Required: ``root``.
    Optional: ``lock_timeout`` (float, default ``1.0``) — write-lock wait timeout (s).
    Optional: ``lock_wait_start`` (float, default ``0.001``) — initial lock-poll
    interval for exponential backoff (s).
    Optional: ``version_validator`` (str, default omitted) — version validation
    strategy passed to ``H5Bag.load()``.  One of ``"exact"``, ``"semantic-minor"``,
    ``"semantic-major"``, ``"none"``.  When omitted, bagofholding's default applies.
    Optional (value backend): ``remaining_depth`` (int, default ``0``).

``"sql"``
    SQL database via SQLAlchemy (:class:`~fleche.storage.Sql`).
    *Call storage only.*  Required: ``url`` (SQLAlchemy connection URL,
    e.g. ``"sqlite:///~/.fleche/calls.db"``).
    Optional: ``echo`` (bool, default ``False``) — log SQL statements.

Example fleche.toml
-------------------

::

    [default]
    cache = "persistent"
    metadata = ["Runtime"]

    [persistent]
    values.type = "cloudpickle"
    values.root = "~/.fleche/values"
    calls.type = "cloudpickle"
    calls.root = "~/.fleche/calls"

    [fast]
    values.type = "memory"
    calls.type = "memory"

    [with_sql_calls]
    values.type = "cloudpickle"
    values.root = "~/.fleche/values"
    calls.type = "sql"
    calls.url = "sqlite:///~/.fleche/calls.db"

"""

from dataclasses import asdict
import tomllib
import logging
from typing import Literal, cast, overload
from pathlib import Path
import os
from typing import Any

from . import storage, metadata, caches

logger = logging.getLogger("fleche.config")

_live_caches: dict[str, caches.Cache] = {}


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
def storage_from_config(d: dict[str, Any], type: Literal["call"]) -> storage.CallStorage: ...

@overload
def storage_from_config(d: dict[str, Any], type: Literal["value"]) -> storage.ValueStorage: ...

def storage_from_config(d: dict[str, Any], type: Literal["call", "value"]) -> storage.ValueStorage | storage.CallStorage:
    """Construct a :class:`~fleche.storage.StorageBackend` from a config dict.

    The dict must contain a ``"type"`` key (case-sensitive, lowercase) and any
    additional parameters required by that storage backend.  The input dict is
    **not** mutated.

    Supported type values and their parameters:

    * ``{"type": "memory"}``
    * ``{"type": "void"}``
    * ``{"type": "pickle", "root": "<path>"}``
      — optional: ``compress``, ``lock_timeout``, ``lock_wait_start``,
      ``secret_key`` (list of hex strings), ``remaining_depth`` (value only)
    * ``{"type": "cloudpickle", "root": "<path>"}``
      — same optional keys as ``"pickle"``
    * ``{"type": "dill", "root": "<path>"}``
      — same optional keys as ``"pickle"``
    * ``{"type": "bagofholding_hdf", "root": "<path>"}``
      — optional: ``lock_timeout``, ``lock_wait_start``,
      ``version_validator``, ``remaining_depth`` (value only)
    * ``{"type": "sql", "url": "<sqlalchemy-url>"}``  *(call storage only)*
      — optional: ``echo``

    See the module docstring for full descriptions of each key.
    """
    d = dict(d)
    backend = d.pop("type")
    match backend:
        case "memory":
            return _STORAGE_NAME_MAPPING[backend, type]({})  # type: ignore
        case "void":
            return _STORAGE_NAME_MAPPING[backend, type]()  # type: ignore
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
    cls = type(s)
    if cls not in _STORAGE_CLASS_TO_NAME and not isinstance(s, storage.Sql):
        raise ValueError(f"Cannot convert storage of type {cls.__name__!r} to config")

    match s:
        case storage.memory.MemoryBackend():
            config = asdict(s)  # type: ignore
            config["type"] = "memory"
            del config["storage"]
        case storage.void.VoidBackend():
            config = asdict(s)  # type: ignore
            config["type"] = "void"
        case storage.pickle_file.PickleFileBackend():
            config = asdict(s)  # type: ignore
            serializer_name = s.dumps.__module__.split(".")[0].lstrip("_")
            if serializer_name not in ("pickle", "dill", "cloudpickle"):
                raise ValueError(f"Unknown PickleFile serializer: {serializer_name!r}")
            config["type"] = serializer_name
            del config["dumps"]
            del config["loads"]
            if config["secret_key"]:
                config["secret_key"] = [k.hex() for k in config["secret_key"]]
            else:
                del config["secret_key"]
            config["root"] = str(config["root"])
        case storage.bagofholding_file.BagOfHoldingH5FileBackend():
            config = asdict(s)  # type: ignore
            config["type"] = "bagofholding_hdf"
            config["root"] = str(config["root"])
            if config.get("version_validator") is None:
                config.pop("version_validator", None)
        case storage.sql.Sql():
            config = {"type": "sql", "url": s.url, "echo": s.echo}
        case _:
            raise ValueError(f"Cannot convert storage of type {cls.__name__!r} to config")
    return config


def cache_from_config(d: "dict[str, Any] | list[dict[str, Any]]") -> caches.BaseCache:
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
        return caches.CacheStack(tuple(cache_from_config(c) for c in d))

    d = dict(d)
    read_only = d.pop("read_only", False)
    max_size = d.pop("max_size", None)

    values_storage = storage_from_config(d["values"], "value")
    calls_storage = storage_from_config(d["calls"], "call")

    if max_size is not None:
        cache: caches.BaseCache = caches.SizeLimitedCache(values=values_storage, calls=calls_storage, max_size=max_size)
    else:
        cache = caches.Cache(values=values_storage, calls=calls_storage)

    if read_only:
        cache = caches.ReadOnlyCache(cache)

    return cache


def cache_to_config(c: caches.BaseCache) -> "dict[str, Any] | list[dict[str, Any]]":
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
        case caches.SizeLimitedCache():
            return {
                "values": storage_to_config(c.values),
                "calls": storage_to_config(c.calls),
                "max_size": c.max_size,
            }
        case caches.Cache():
            return {
                "values": storage_to_config(c.values),
                "calls": storage_to_config(c.calls),
            }
        case caches.ReadOnlyCache():
            inner = c.cache
            if not isinstance(inner, (caches.Cache, caches.SizeLimitedCache)):
                raise ValueError(
                    f"ReadOnlyCache wrapping {type(inner).__name__!r} cannot be serialised to config"
                )
            d = cache_to_config(inner)
            assert isinstance(d, dict)
            d["read_only"] = True
            return d
        case caches.CacheStack():
            return cast("list[dict[str, Any]]", [cache_to_config(s) for s in c.stack])
        case _:
            raise ValueError(f"Cannot convert cache of type {type(c).__name__!r} to config")


def _create_cache(cache_config: dict[str, Any]) -> caches.Cache:
    values = storage_from_config(cache_config["values"], "value")
    calls = storage_from_config(cache_config["calls"], "call")
    return caches.Cache(values=values, calls=calls)


def load_cache_config(name: str | None = None) -> caches.Cache:
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
        cache = caches.Cache(storage.ValueMemory({}), storage.CallMemory({}))
        _live_caches[name] = cache
        return cache

    if name == "void":
        cache = caches.Cache(storage.ValueVoid(), storage.CallVoid())
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
        return caches.Cache(storage.ValueMemory({}), storage.CallMemory({}))

    config = _load_config(path)

    cache_name = name
    cache_config = None

    if cache_name is None:
        if "default" not in config or "cache" not in config["default"]:
            logger.warning("No default cache configured. Using default memory cache.")
            return caches.Cache(storage.ValueMemory({}), storage.CallMemory({}))

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
            return caches.Cache(storage.ValueMemory({}), storage.CallMemory({}))
        cache_config = config[cache_name]

    cache = _create_cache(cache_config)
    _live_caches[cache_name] = cache
    return cache
