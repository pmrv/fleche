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

``"pickle"``
    Filesystem backend serialised with the standard ``pickle`` module
    (:class:`~fleche.storage.ValuePickleFile` /
    :class:`~fleche.storage.CallPickleFile`).
    Required: ``root`` (path to storage directory).
    Optional: ``compress`` (bool, default ``False``) — gzip-compress files.
    Optional: ``lock_timeout`` (float, default ``1.0``) — file-lock acquisition timeout (s).
    Optional: ``secret_key`` (list of hex strings) — HMAC-SHA256 signing keys;
    each element is a hex-encoded byte string (same format as ``FLECHE_SECRET_KEY``).
    If omitted, falls back to the ``FLECHE_SECRET_KEY`` environment variable.
    Optional (value backend): ``remaining_depth`` (int, default ``0``).

``"cloudpickle"``
    Filesystem backend serialised with ``cloudpickle`` — handles more
    complex Python objects than ``pickle``.
    Required: ``root``.
    Optional: ``compress`` (bool, default ``False``) — gzip-compress files.
    Optional: ``lock_timeout`` (float, default ``1.0``) — file-lock acquisition timeout (s).
    Optional: ``secret_key`` (list of hex strings) — same as ``"pickle"``.
    Optional (value backend): ``remaining_depth`` (int, default ``0``).

``"dill"``
    Filesystem backend serialised with ``dill``.
    Required: ``root``.
    Optional: ``compress`` (bool, default ``False``) — gzip-compress files.
    Optional: ``lock_timeout`` (float, default ``1.0``) — file-lock acquisition timeout (s).
    Optional: ``secret_key`` (list of hex strings) — same as ``"pickle"``.
    Optional (value backend): ``remaining_depth`` (int, default ``0``).

``"bagofholding_hdf"``
    HDF5-backed storage via the ``bagofholding`` library
    (:class:`~fleche.storage.ValueBagOfHoldingH5File` /
    :class:`~fleche.storage.CallBagOfHoldingH5File`).
    Required: ``root``.
    Optional: ``lock_timeout`` (float, default ``1.0``) — file-lock acquisition timeout (s).
    Optional: ``version_validator`` (str, default omitted) — version validation
    strategy passed to :meth:`bagofholding:bagofholding.h5.bag.H5Bag.load`.  One of ``"exact"``, ``"semantic-minor"``,
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

    # SizeLimitedCache — evicts oldest entries once 100 entries are stored
    [limited]
    values.type = "memory"
    calls.type = "memory"
    max_size = 100

    # ReadOnlyCache — loads from storage but never writes new results
    [readonly]
    values.type = "cloudpickle"
    values.root = "~/.fleche/values"
    calls.type = "cloudpickle"
    calls.root = "~/.fleche/calls"
    read_only = true

    # CacheStack — TOML array-of-tables; saves to the bottom layer,
    # loads top-down and back-fills hits to the bottom
    [[mystack]]
    values.type = "memory"
    calls.type = "memory"

    [[mystack]]
    values.type = "cloudpickle"
    values.root = "~/.fleche/values"
    calls.type = "cloudpickle"
    calls.root = "~/.fleche/calls"

Config file discovery
---------------------

When the active cache or default metadata is loaded, fleche walks from the
current working directory upward, picking up every ``fleche.toml`` and
``.fleche.toml`` it encounters.  The walk stops at ``$HOME`` (inclusive) or
at the filesystem root, whichever comes first.  If ``XDG_CONFIG_HOME`` is
set, ``$XDG_CONFIG_HOME/fleche/cache.toml`` is appended as a final
lowest-priority layer.

All discovered files are **shallow-merged** at the top level: files closer
to the CWD win, and a closer file's top-level table fully replaces the
same key in a farther file (tables are *not* recursively merged).
"""

import dataclasses
from dataclasses import asdict
import tomllib
import logging
from typing import Literal, cast, overload
from pathlib import Path
import os
from typing import Any

from . import storage, metadata, caches

logger = logging.getLogger("fleche.config")

_live_caches: dict[str | None, caches.BaseCache] = {}


def _load_config(path: Path) -> dict[str, Any]:
    try:
        with open(path, "rb") as f:
            return tomllib.load(f)
    except Exception as e:
        logger.error("Failed to load configuration from %s: %s", path, e)
        return {}


def _collect_config_paths() -> list[Path]:
    """Return config paths in priority order (closest first, lowest last).

    Walks from the current working directory up to ``$HOME`` (inclusive),
    collecting any ``fleche.toml`` or ``.fleche.toml`` files encountered.  If
    the walk reaches the filesystem root without crossing ``$HOME`` (or
    ``$HOME`` is unset), it stops at the root.  Finally,
    ``$XDG_CONFIG_HOME/fleche/cache.toml`` is appended as the lowest-priority
    fallback when ``XDG_CONFIG_HOME`` is set.
    """
    paths: list[Path] = []

    try:
        home = Path.home().absolute()
    except (RuntimeError, KeyError):
        home = None

    current = Path.cwd().absolute()
    while True:
        for name in ("fleche.toml", ".fleche.toml"):
            candidate = current / name
            if candidate.exists():
                paths.append(candidate)
        if home is not None and current == home:
            break
        parent = current.parent
        if parent == current:
            break
        current = parent

    if "XDG_CONFIG_HOME" in os.environ:
        xdg_path = Path(os.environ["XDG_CONFIG_HOME"]) / "fleche" / "cache.toml"
        if xdg_path.exists() and xdg_path not in paths:
            paths.append(xdg_path)

    return paths


def _load_merged_config() -> dict[str, Any]:
    """Load and shallow-merge all config files on the walk path.

    Files closer to the CWD override files farther away.  Top-level keys
    from the closest file fully replace the same key from any farther file
    (no recursive table merging).
    """
    merged: dict[str, Any] = {}
    for path in reversed(_collect_config_paths()):
        config = _load_config(path)
        merged.update(config)
    return merged


def load_default_metadata():
    """
    Load the default metadata from the merged configuration files.
    """
    config = _load_merged_config()

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
      — optional: ``compress``, ``lock_timeout``,
      ``secret_key`` (list of hex strings), ``remaining_depth`` (value only)
    * ``{"type": "cloudpickle", "root": "<path>"}``
      — same optional keys as ``"pickle"``
    * ``{"type": "dill", "root": "<path>"}``
      — same optional keys as ``"pickle"``
    * ``{"type": "bagofholding_hdf", "root": "<path>"}``
      — optional: ``lock_timeout``,
      ``version_validator``, ``remaining_depth`` (value only)
    * ``{"type": "sql", "url": "<sqlalchemy-url>"}``  *(call storage only)*
      — optional: ``echo``

    See the module docstring for full descriptions of each key.
    """
    d = dict(d)
    backend = d.pop("type")
    match backend:
        case "memory":
            return _STORAGE_NAME_MAPPING[backend, type]({}, **d)  # type: ignore
        case "void":
            return _STORAGE_NAME_MAPPING[backend, type]()  # type: ignore
        case "bagofholding_hdf" | "pickle" | "dill" | "cloudpickle":
            return _STORAGE_NAME_MAPPING[backend, type](**d)
        case "sql" if type == "call":
            return storage.Sql(**d)
        case _:
            raise ValueError(f"Unknown storage type '{backend}' for {type} storage!")


def _asdict_init_only(obj) -> dict[str, Any]:
    """Like ``dataclasses.asdict()`` but restricted to ``init=True`` fields.

    ``init=False`` fields are internal state (locks, caches) that must not
    appear in serialised config.
    """
    non_init = {f.name for f in dataclasses.fields(obj) if not f.init}
    return {k: v for k, v in asdict(obj).items() if k not in non_init}


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
            config = _asdict_init_only(s)
            config["type"] = "memory"
            del config["storage"]
        case storage.void.VoidBackend():
            config = _asdict_init_only(s)
            config["type"] = "void"
        case storage.pickle_file.PickleFileBackend():
            config = _asdict_init_only(s)
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
            config = _asdict_init_only(s)
            config["type"] = "bagofholding_hdf"
            config["root"] = str(config["root"])
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

    Examples:

        >>> c = cache_from_config({"values": {"type": "memory"}, "calls": {"type": "memory"}})
        >>> type(c).__name__
        'Cache'

        >>> c = cache_from_config({"values": {"type": "memory"}, "calls": {"type": "memory"}, "max_size": 100})
        >>> isinstance(c, caches.SizeLimitedCache)
        True

        >>> c = cache_from_config({"values": {"type": "memory"}, "calls": {"type": "memory"}, "read_only": True})
        >>> isinstance(c, caches.ReadOnlyCache)
        True

        >>> c = cache_from_config([{"values": {"type": "memory"}, "calls": {"type": "memory"}}, {"values": {"type": "void"}, "calls": {"type": "void"}}])
        >>> isinstance(c, caches.CacheStack)
        True
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


def _default_memory_cache(name: str | None, reason: str | None = None) -> caches.Cache:
    """Return (and intern) a fresh in-memory cache, optionally logging the fallback reason."""
    if reason is not None:
        logger.warning("Using default memory cache: %s", reason)
    cache = caches.Cache(storage.ValueMemory({}), storage.CallMemory({}))
    _live_caches[name] = cache
    return cache


def load_cache_config(name: str | None = None) -> caches.BaseCache:
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
        return _default_memory_cache("memory")

    if name == "void":
        cache = caches.Cache(storage.ValueVoid(), storage.CallVoid())
        _live_caches[name] = cache
        return cache

    config = _load_merged_config()
    if not config:
        reason = f"no config file found (name={name!r})" if name is not None else "no config file found"
        return _default_memory_cache(name, reason)

    if name is None:
        if "default" not in config or "cache" not in config["default"]:
            return _default_memory_cache(None, "no default cache configured")
        default_cache = config["default"]["cache"]
        if isinstance(default_cache, str):
            return load_cache_config(default_cache)
        cache_name, cache_config = "default", default_cache
    else:
        if name not in config:
            return _default_memory_cache(name, f"cache {name!r} not found in configuration")
        cache_name, cache_config = name, config[name]

    cache = cache_from_config(cache_config)
    _live_caches[cache_name] = cache
    return cache
