"""
Configuration system for fleche.

Storage type names
------------------

The ``type`` key in a storage config dict is case-sensitive and uses the
following **lowercase** identifiers:

``"memory"``
    In-memory dict (:class:`~fleche.storage.ValueMemory` /
    :class:`~fleche.storage.CallMemory`).  No required keys.
    Optional (value backend): ``remaining_depth`` (int, default ``1``).

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
    Optional (value backend): ``remaining_depth`` (int, default ``1``).

``"cloudpickle"``
    Filesystem backend serialised with ``cloudpickle`` — handles more
    complex Python objects than ``pickle``.
    Required: ``root``.
    Optional: ``compress`` (bool, default ``False``) — gzip-compress files.
    Optional: ``lock_timeout`` (float, default ``1.0``) — file-lock acquisition timeout (s).
    Optional: ``secret_key`` (list of hex strings) — same as ``"pickle"``.
    Optional (value backend): ``remaining_depth`` (int, default ``1``).

``"dill"``
    Filesystem backend serialised with ``dill``.
    Required: ``root``.
    Optional: ``compress`` (bool, default ``False``) — gzip-compress files.
    Optional: ``lock_timeout`` (float, default ``1.0``) — file-lock acquisition timeout (s).
    Optional: ``secret_key`` (list of hex strings) — same as ``"pickle"``.
    Optional (value backend): ``remaining_depth`` (int, default ``1``).

``"bagofholding_hdf"``
    HDF5-backed storage via the ``bagofholding`` library
    (:class:`~fleche.storage.ValueBagOfHoldingH5File` /
    :class:`~fleche.storage.CallBagOfHoldingH5File`).
    Required: ``root``.
    Optional: ``lock_timeout`` (float, default ``1.0``) — file-lock acquisition timeout (s).
    Optional: ``version_validator`` (str, default omitted) — version validation
    strategy passed to :meth:`bagofholding:bagofholding.h5.bag.H5Bag.load`.  One of ``"exact"``, ``"semantic-minor"``,
    ``"semantic-major"``, ``"none"``.  When omitted, bagofholding's default applies.
    Optional: ``prefix_length`` (int, default ``2``) — keys sharing the first
    ``prefix_length`` characters are multiplexed as sibling groups (named by
    the full key) into one file at ``root/{key[:prefix_length]}.h5``, instead
    of each key getting its own file.  ``0`` keeps one file per key; ``None``
    (only settable from Python; TOML cannot express ``None``) infers the
    length from the files already present in ``root``, falling back to the
    default on an empty root.  The value is checked against existing files at
    construction; re-shard a live storage with
    :meth:`~fleche.storage.bagofholding_file.BagOfHoldingH5FileBackend.refix`
    or repair a mixed root with
    :meth:`~fleche.storage.bagofholding_file.BagOfHoldingH5FileBackend.consolidate`.
    Optional (value backend): ``remaining_depth`` (int, default ``1``).

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

    # CachePool — a read-only collection of caches, queried as one; never
    # writes to any member.  Use a dict with a `pool` array-of-tables.
    [[mypool.pool]]
    values.type = "cloudpickle"
    values.root = "~/.fleche/values"
    calls.type = "cloudpickle"
    calls.root = "~/.fleche/calls"

    [[mypool.pool]]
    values.type = "cloudpickle"
    values.root = "~/teammate/.fleche/values"
    calls.type = "cloudpickle"
    calls.root = "~/teammate/.fleche/calls"

    # SshCache — share results with another machine over SSH.  The remote
    # runs `python -m fleche remote --serve` and proxies into its own
    # configured cache.  Compose with a local cache by stacking two
    # entries (saves go to the first entry; reads fall back to the SSH
    # remote and back-fill hits into the local layer).
    [[shared]]
    values.type = "cloudpickle"
    values.root = "~/.fleche/values"
    calls.type = "cloudpickle"
    calls.root = "~/.fleche/calls"

    [[shared]]
    type = "ssh"
    host = "user@bigpc.example.com"
    cache_name = "shared"               # optional: named cache on remote
    python = "python3"                  # optional: remote python interpreter
    ssh_options = ["-o", "ControlMaster=auto",
                   "-o", "ControlPath=~/.ssh/cm-%r@%h:%p",
                   "-o", "ControlPersist=10m"]
    setup_commands = ["module load python/3.11",  # optional: shell snippets
                      "source ~/.venv/bin/activate"]  # run before the server
    workdir = "~/project"               # optional: cd here before launching
                                        # the server, so the remote can import
                                        # the project's local modules

Cache templates
---------------

For the common cases a full ``values``/``calls`` pair is more verbose than it
needs to be.  A cache config may instead use a ``template`` key naming a
predefined shape, plus the (required) storage arguments that shape needs::

    [terse]
    template = "cloudpickle"
    root = "~/.fleche"          # -> values at root/values, calls at root/calls

    [sqlbacked]
    template = "sql"            # filesystem values + SQL call storage
    root = "~/.fleche"          # -> values at root/values,
                                #    calls at sqlite:///root/calls.db

Symmetric templates (``memory``, ``pickle``, ``cloudpickle``, ``dill``,
``bagofholding_hdf``) use the same backend for both values and calls; the
filesystem ones split ``root`` into ``root/values`` and ``root/calls``.  The
``sql`` template stores values on the filesystem under ``root/values`` and
calls in a SQL database; its value backend defaults to ``bagofholding_hdf``
(override with ``values = "pickle"`` etc.) and its call ``url`` defaults to
``sqlite:///root/calls.db`` (override with an explicit ``url``).
``read_only``/``max_size`` may be combined with a template.
Anything a template does not cover (mixed backends, per-backend options like
``compress`` or ``secret_key``) is expressed with an explicit
``values``/``calls`` config instead.

Config file discovery
---------------------

When the active cache or default metadata is loaded, fleche walks from the
current working directory upward, picking up every ``fleche.toml`` it
encounters.  The walk stops at ``$HOME`` (inclusive) or at the filesystem
root, whichever comes first.  ``$XDG_CONFIG_HOME/fleche/cache.toml``
(defaulting to ``~/.config/fleche/cache.toml`` per the XDG base
directory spec when ``XDG_CONFIG_HOME`` is unset or empty) is appended
as a final lowest-priority layer.

All discovered files are **shallow-merged** at the top level: files closer
to the CWD win, and a closer file's top-level table fully replaces the
same key in a farther file (tables are *not* recursively merged).

Stopping the walk
-----------------

A ``fleche.toml`` can declare ``root = true`` in its ``[default]`` table to
act as the top of the config hierarchy.  When the walk reaches such a file,
files farther up the tree (and the ``$XDG_CONFIG_HOME`` fallback) are *not*
merged in — only the ``root`` file and any files closer to the CWD
contribute.  This lets a project pin its configuration without inheriting
whatever ``fleche.toml`` happens to live in a parent directory or ``$HOME``::

    [default]
    cache = "persistent"
    root = true              # ignore any fleche.toml farther up the tree
"""

import tomllib
import logging
from typing import Callable, Literal, cast, overload
from pathlib import Path
import os
from typing import Any

from . import storage, metadata, caches
from .remote import SshCache

logger = logging.getLogger("fleche.config")

_live_caches: dict[str | None, caches.BaseCache] = {}


def _load_config(path: Path) -> dict[str, Any]:
    try:
        with open(path, "rb") as f:
            return tomllib.load(f)
    except Exception as e:
        logger.error("Failed to load configuration from %s: %s", path, e, exc_info=True)
        return {}


def _collect_config_paths() -> list[Path]:
    """Return config paths in priority order (closest first, lowest last).

    Walks from the current working directory up to ``$HOME`` (inclusive),
    collecting any ``fleche.toml`` files encountered.  If the walk reaches
    the filesystem root without crossing ``$HOME`` (or ``$HOME`` is unset),
    it stops at the root.  Finally,
    ``$XDG_CONFIG_HOME/fleche/cache.toml`` is appended as the lowest-priority
    fallback.  Per the XDG base directory spec, an unset or empty
    ``XDG_CONFIG_HOME`` defaults to ``$HOME/.config``.
    """
    paths: list[Path] = []

    try:
        home = Path.home().absolute()
    except (RuntimeError, KeyError):
        home = None

    current = Path.cwd().absolute()
    while True:
        candidate = current / "fleche.toml"
        if candidate.exists():
            paths.append(candidate)
        if home is not None and current == home:
            break
        parent = current.parent
        if parent == current:
            break
        current = parent

    xdg_base = os.environ.get("XDG_CONFIG_HOME") or (
        str(home / ".config") if home is not None else ""
    )
    if xdg_base:
        xdg_path = Path(xdg_base) / "fleche" / "cache.toml"
        if xdg_path.exists() and xdg_path not in paths:
            paths.append(xdg_path)

    return paths


def _is_root_config(config: dict[str, Any]) -> bool:
    """Whether ``config`` declares ``root = true`` in its ``[default]`` table.

    A file that sets ``[default].root`` acts as the top of the config
    hierarchy: files farther up the walk (and the XDG fallback) are not
    merged in.
    """
    default = config.get("default")
    return isinstance(default, dict) and bool(default.get("root", False))


def _load_merged_config() -> dict[str, Any]:
    """Load and shallow-merge all config files on the walk path.

    Files closer to the CWD override files farther away.  Top-level keys
    from the closest file fully replace the same key from any farther file
    (no recursive table merging).

    The walk stops at the closest file that sets ``[default].root = true``:
    that file acts as the top of the hierarchy, and any files farther up
    (including the XDG fallback) are ignored.
    """
    merged: dict[str, Any] = {}
    for path in _collect_config_paths():  # closest first
        config = _load_config(path)
        # setdefault, not update: a closer file already in `merged` wins over
        # the same top-level key in a farther file.
        for key, value in config.items():
            merged.setdefault(key, value)
        if _is_root_config(config):
            break
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
        cls = metadata.CONFIGURABLE.get(name)
        if cls is None:
            raise ValueError(f"Unknown or non-configurable metadata type in config: {name}")
        meta_objects.append(cls())

    return tuple(meta_objects)

@overload
def storage_from_config(d: dict[str, Any], type: Literal["call"]) -> storage.CallStorage: ...

@overload
def storage_from_config(d: dict[str, Any], type: Literal["value"]) -> storage.ValueStorage: ...

def storage_from_config(d: dict[str, Any], type: Literal["call", "value"]) -> storage.ValueStorage | storage.CallStorage:
    """Construct a :class:`~fleche.storage.StorageBackend` from a config dict.

    The dict must contain a ``"type"`` key (case-sensitive, lowercase) and any
    additional parameters required by that storage backend.  The input dict is
    **not** mutated. ``"type"`` is looked up against the backends registered
    via :func:`fleche.storage.register_storage`.

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
      ``version_validator``, ``prefix_length``, ``remaining_depth`` (value only)
    * ``{"type": "sql", "url": "<sqlalchemy-url>"}``  *(call storage only)*
      — optional: ``echo``

    See the module docstring for full descriptions of each key.
    """
    d = dict(d)
    backend = d.pop("type")
    ctor = storage.get_storage_constructor(backend, type)
    if ctor is None:
        raise ValueError(f"Unknown storage type {backend!r} for {type} storage!")
    return cast("storage.ValueStorage | storage.CallStorage", ctor(**d))


def storage_to_config(s: storage.ValueStorage | storage.CallStorage) -> dict[str, Any]:
    """Convert a Storage instance to a config dict (inverse of ``storage_from_config``).

    The returned dict contains a ``"type"`` key and any additional parameters
    needed to reconstruct the storage via :func:`storage_from_config`.
    Delegates to the storage's own ``to_config()`` (see
    ``StorageBackend.to_config``).

    Raises:
        ValueError: for a storage that cannot name itself in a config — one
            that defines no ``to_config`` at all, or whose exact class was
            never passed to :func:`fleche.storage.register_storage`.
    """
    to_config = getattr(s, "to_config", None)
    if to_config is None:
        raise ValueError(f"Cannot convert storage of type {type(s).__name__!r} to config")
    return to_config()


def _template_symmetric_transient(style: str) -> "Callable[..., tuple[dict[str, Any], dict[str, Any]]]":
    """Both value and call storage use the same transient backend (no ``root``)."""
    def build() -> "tuple[dict[str, Any], dict[str, Any]]":
        return {"type": style}, {"type": style}
    return build


def _template_symmetric_file(style: str) -> "Callable[..., tuple[dict[str, Any], dict[str, Any]]]":
    """Both value and call storage use the same filesystem backend under ``root``.

    Values go to ``root/values`` and calls to ``root/calls`` so the two never
    collide in one directory.  The ``root`` is kept as a string (``~`` and
    relative paths are resolved later by the backend).
    """
    def build(root: str) -> "tuple[dict[str, Any], dict[str, Any]]":
        base = Path(root)
        return (
            {"type": style, "root": str(base / "values")},
            {"type": style, "root": str(base / "calls")},
        )
    return build


def _template_sql(default_value_style: str = "bagofholding_hdf") -> "Callable[..., tuple[dict[str, Any], dict[str, Any]]]":
    """Filesystem values paired with SQL call storage, both derived from ``root``.

    Values go to ``root/values`` using the ``values`` backend (any filesystem
    value backend — ``pickle``/``cloudpickle``/``dill``/``bagofholding_hdf`` —
    defaulting to ``bagofholding_hdf``).  The SQL connection ``url`` defaults to
    a SQLite database at ``root/calls.db`` but may be overridden explicitly.
    """
    def build(
        root: str, values: str = default_value_style, url: "str | None" = None
    ) -> "tuple[dict[str, Any], dict[str, Any]]":
        base = Path(root)
        return (
            {"type": values, "root": str(base / "values")},
            {"type": "sql", "url": url if url is not None else f"sqlite:///{base / 'calls.db'}"},
        )
    return build


# Named cache templates.  Each entry maps a ``template`` string to a builder
# that turns the remaining (required) config keys into a ``(values, calls)``
# pair of storage configs.  The builders take explicit keyword arguments so a
# missing or unexpected key surfaces as a clear error (see cache_from_config).
_CACHE_TEMPLATES: "dict[str, Callable[..., tuple[dict[str, Any], dict[str, Any]]]]" = {
    "memory": _template_symmetric_transient("memory"),
    "pickle": _template_symmetric_file("pickle"),
    "cloudpickle": _template_symmetric_file("cloudpickle"),
    "dill": _template_symmetric_file("dill"),
    "bagofholding_hdf": _template_symmetric_file("bagofholding_hdf"),
    "sql": _template_sql(),
}


def _cache_from_template(d: "dict[str, Any]") -> caches.BaseCache:
    """Expand a ``{"template": ..., ...}`` dict into a full cache config.

    The builder for the named template consumes the storage arguments (the
    "union of the sub-args required to fill the value and call storage
    configs") and produces explicit ``values``/``calls`` sections.  Cache-level
    modifiers (``read_only``, ``max_size``) are preserved and applied by
    recursing through :func:`cache_from_config`.
    """
    d = dict(d)
    template = d.pop("template")
    builder = _CACHE_TEMPLATES.get(template)
    if builder is None:
        raise ValueError(
            f"Unknown cache template {template!r}; "
            f"choose from {sorted(_CACHE_TEMPLATES)}"
        )

    # Cache-level modifiers pass through to the expanded config rather than the
    # storage builder.
    read_only = d.pop("read_only", False)
    max_size = d.pop("max_size", None)

    try:
        values_config, calls_config = builder(**d)
    except TypeError as e:
        raise ValueError(
            f"Invalid arguments for cache template {template!r}: {e}. "
            f"Use an explicit 'values'/'calls' config for anything the "
            f"template doesn't cover."
        ) from None

    expanded: dict[str, Any] = {"values": values_config, "calls": calls_config}
    if read_only:
        expanded["read_only"] = read_only
    if max_size is not None:
        expanded["max_size"] = max_size
    return cache_from_config(expanded)


def cache_from_config(d: "dict[str, Any] | list[dict[str, Any]]") -> caches.BaseCache:
    """Construct a :class:`~fleche.caches.BaseCache` from a config dict or list.

    The cache type is determined **implicitly** from the shape of the input:

    - A **list** of dicts is treated as a :class:`~fleche.caches.CacheStack`,
      with each element processed recursively.
    - A **dict** containing a ``pool`` key (a list of dicts) creates a
      read-only :class:`~fleche.caches.CachePool`, with each element of the
      list processed recursively.
    - A **dict** containing a ``template`` key is expanded via a named template
      (see :data:`_CACHE_TEMPLATES`) into an equivalent ``values``/``calls``
      config.  Templates are a shorthand for the common cases: the symmetric
      backends (``memory``, ``pickle``, ``cloudpickle``, ``dill``,
      ``bagofholding_hdf``) use one backend for both values and calls, and
      ``sql`` pairs a filesystem value backend with SQL call storage.
      Filesystem templates require a ``root``; the ``sql`` template requires a
      ``root`` and optionally takes ``values`` (the value backend, default
      ``bagofholding_hdf``) and ``url`` (the SQL URL, default
      ``sqlite:///root/calls.db``).  ``read_only``/``max_size`` may be
      combined with a template.
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

        >>> c = cache_from_config({"template": "memory"})
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

    if "pool" in d:
        return caches.CachePool(tuple(cache_from_config(c) for c in d["pool"]))

    if "template" in d:
        return _cache_from_template(d)

    d = dict(d)
    if d.get("type") == "ssh":
        d.pop("type")
        return SshCache(**d)
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
    - :class:`~fleche.caches.CachePool` → dict with a ``"pool"`` list of dicts

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
        case caches.CachePool():
            return {"pool": [cache_to_config(m) for m in c.caches]}
        case _:
            if isinstance(c, SshCache):
                d: dict[str, Any] = {"type": "ssh", "host": c.host}
                if c.cache_name is not None:
                    d["cache_name"] = c.cache_name
                if c.python != "python3":
                    d["python"] = c.python
                if c.ssh_options:
                    d["ssh_options"] = list(c.ssh_options)
                if c.setup_commands:
                    d["setup_commands"] = list(c.setup_commands)
                if c.workdir is not None:
                    d["workdir"] = c.workdir
                return d
            raise ValueError(f"Cannot convert cache of type {type(c).__name__!r} to config")


def _default_memory_cache(name: str | None, reason: str | None = None) -> caches.Cache:
    """Return (and intern) a fresh in-memory cache, optionally logging the fallback reason."""
    if reason is not None:
        logger.info("Using default memory cache: %s", reason)
    cache = caches.Cache(storage.ValueMemory({}), storage.CallMemory({}))
    _live_caches[name] = cache
    return cache


def load_cache_config(name: str | None = None) -> caches.BaseCache:
    """
    Load a cache from the configuration file.

    If name is None, the default cache is loaded.
    The names 'memory', 'void', and 'default' are special-cased: 'memory'
    and 'void' return transient backends; 'default' resolves to whichever
    cache the config file designates as the default (equivalent to calling
    this function with ``name=None``).

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

    if name == "default":
        cache = load_cache_config(None)
        _live_caches["default"] = cache
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
            cache = load_cache_config(default_cache)
        else:
            cache = cache_from_config(default_cache)
    else:
        if name not in config:
            return _default_memory_cache(name, f"cache {name!r} not found in configuration")
        cache = cache_from_config(config[name])

    # Intern under the requested name (the same key callers look up by, ``None``
    # for the default cache) so repeated lookups return the same instance rather
    # than rebuilding it — otherwise resolving the default would reconstruct the
    # cache every time, re-spawning an SshCache subprocess, reopening file
    # handles, etc.  A string-alias default also interns under its own name via
    # the recursive call above, so both keys map to the one instance.
    _live_caches[name] = cache
    return cache
