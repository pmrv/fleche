Configuration
=============

``fleche`` discovers configuration by walking the filesystem from the
current working directory upward, collecting every ``fleche.toml`` it
encounters.  The walk stops at ``$HOME`` (inclusive) or at the filesystem
root, whichever comes first.  ``$XDG_CONFIG_HOME/fleche/cache.toml`` is
then appended as a final lowest-priority layer, defaulting to
``~/.config/fleche/cache.toml`` when ``$XDG_CONFIG_HOME`` is unset or
empty (per the XDG base directory spec).

All discovered files are **shallow-merged** at the top level: files closer
to the current directory win, and a closer file's top-level table fully
replaces the same key in a farther file (tables are *not* recursively
merged).  This makes it easy to keep a base config at ``~/fleche.toml``
(or in XDG) and override individual cache definitions in project
subdirectories.

A file can opt out of this upward inheritance by setting ``root = true`` in
its ``[default]`` table (see :ref:`the default section <default-section>`
below).  The walk stops at the closest such file: files farther up the tree
— and the ``$XDG_CONFIG_HOME`` fallback — are not merged in.

If no configuration file is discovered, ``fleche`` falls back to a default
in-memory cache.

A relative ``root`` (storage/template) or ``url`` (``sql`` calls) is resolved
against the directory containing the ``fleche.toml`` that declared it, not
against the process's current working directory. This is what makes a
checked-in, machine-portable config file resolve to the *same* cache location
no matter which subdirectory it is read from during the walk above. Absolute
paths and ``~``-prefixed paths are unaffected. This resolution only happens
for paths read from a config file — a ``root``/``url`` passed directly to
``cache_from_config`` or ``storage_from_config`` still resolves against the
CWD, as it always has.

Reserved Cache Names
--------------------

``memory``
~~~~~~~~~~

The name ``memory`` is a reserved cache name. When requested, ``fleche`` will provide a
transient in-memory cache. The cache object is interned (the same instance is reused on
every call to ``cache("memory")``), so data stored in it persists for the lifetime of
the process.  It is **not** shared with other processes and is lost when the current
process exits.

Note that ``with cache("memory"):`` makes the memory cache active *only for the duration
of the* ``with`` *block* — the previous cache is restored on exit.  To make the memory
cache sticky (active until explicitly changed), discard the returned context manager::

   cache("memory")   # sticky — memory cache stays active

Example using the context-manager form to temporarily switch to memory caching:

.. code-block:: pycon

   >>> from fleche import cache
   >>> with cache("memory"):
   ...     # The memory cache is the active cache inside this block.
   ...     # Results stored here persist for the process lifetime via the interned instance,
   ...     # but after the block exits the previous active cache is restored.
   ...     ...

``void``
~~~~~~~~

The name ``void`` is a reserved cache name. When requested, ``fleche`` will provide a no-op cache that discards all stored values. This is useful for disabling caching entirely without changing your code.

Example:

.. code-block:: pycon

   >>> from fleche import cache
   >>> with cache("void"):
   ...     # Results will not be cached at all. Every call executes the function.
   ...     ...

``default``
~~~~~~~~~~~

The name ``default`` is a reserved cache name. When requested, ``fleche`` activates
whichever cache the configuration file designates as the default — equivalent to
the cache that is active at process start.  This is **not** the same as passing
``None`` to :func:`~fleche.state.cache`, which returns the *currently active* cache
without changing anything.

.. code-block:: pycon

   >>> from fleche import cache
   >>> with cache("default"):
   ...     # The config-file default cache is active inside this block.
   ...     ...

.. _default-section:

The ``[default]`` section
-------------------------

The ``[default]`` section is used to configure the default behavior of ``fleche``.

``cache``
~~~~~~~~~

The ``cache`` key specifies the name of the default cache to use.

Example:

.. code-block:: toml

   [default]
   cache = "mycache"

``metadata``
~~~~~~~~~~~~

The ``metadata`` key specifies the default metadata chain to use. This is a list of strings, where each string is the name of a metadata class from the ``fleche.metadata`` module.  When this key is omitted, ``fleche`` defaults to ``["Runtime"]``, so :class:`~fleche.metadata.Runtime` timing information is collected automatically.

Example:

.. code-block:: toml

   [default]
   metadata = ["Runtime"]

**Note:** The ``Tags`` metadata cannot be configured from the config file, as it requires arguments.

``root``
~~~~~~~~

The ``root`` key is a boolean (default ``false``) that marks this file as the
top of the config hierarchy.  When set to ``true``, the discovery walk stops
here: any ``fleche.toml`` farther up the directory tree, along with the
``$XDG_CONFIG_HOME`` fallback, is ignored.  Files *closer* to the current
directory are still merged on top as usual.

Use it to pin a
project's configuration so it does not inherit whatever ``fleche.toml``
happens to live in a parent directory or ``$HOME``.

Example:

.. code-block:: toml

   [default]
   cache = "mycache"
   root = true

Cache sections
--------------

You can define multiple cache configurations in the same file, each in its own section.

Each cache section must define two storage backends: ``values`` and ``calls``. ``values`` is used to store the results of function calls, and ``calls`` is used to store the function call details.

.. _cache-templates:

Cache templates
~~~~~~~~~~~~~~~

A **template** is a shorthand for a whole cache section. Instead of spelling
out separate ``values`` and ``calls`` backends, name a ``template`` and give
it a handful of keys; fleche expands that into the full ``values`` / ``calls``
configuration. ``read_only`` and ``max_size`` may be added alongside any
template. Anything a template does not cover — mixed backends, or per-backend
options such as ``compress`` or ``secret_key`` — is written out with the
explicit ``values`` / ``calls`` form described below.

Two families of template are available.

**Symmetric templates** use a single backend for both ``values`` and
``calls``: ``memory``, ``pickle``, ``cloudpickle``, ``dill``, and
``bagofholding_hdf``. The filesystem ones take a single ``root`` and split it
into ``root/values`` and ``root/calls``; ``memory`` takes no further keys.

.. code-block:: toml

   [terse]
   template = "cloudpickle"     # values -> root/values, calls -> root/calls
   root = "~/.fleche"

**The sql template** stores values on the filesystem and calls in a SQL
database. It accepts:

.. list-table::
   :header-rows: 1
   :widths: 15 15 70

   * - Key
     - Required
     - Meaning
   * - ``root``
     - yes
     - Base directory; values are stored under ``root/values``.
   * - ``values``
     - no
     - Value storage backend, default ``bagofholding_hdf``. Any filesystem
       backend: ``pickle`` / ``cloudpickle`` / ``dill`` / ``bagofholding_hdf``.
   * - ``url``
     - no
     - SQLAlchemy URL for call storage, default ``sqlite:///root/calls.db``.

.. code-block:: toml

   [sqlbacked]
   template = "sql"
   root = "~/.fleche"           # values -> root/values,
                                # calls -> sqlite:///root/calls.db

In Python, build a cache from the same config with
:meth:`~fleche.caches.BaseCache.from_config` and activate it with ``cache``::

   from fleche import cache
   from fleche.caches import Cache

   cache(Cache.from_config({"template": "cloudpickle", "root": "~/.fleche"}))

Storage backends
~~~~~~~~~~~~~~~~

Each storage backend is configured using a ``type`` key, see the table below. Other keys in the same dict are
passed as keyword arguments to the storage constructor.

Example:

.. code-block:: toml

   [mycache]
   values.type = "memory"
   calls.type = "memory"

Available storage types
~~~~~~~~~~~~~~~~~~~~~~~

.. list-table::
   :header-rows: 1
   :widths: 20 35 15 30

   * - Type
     - Description
     - Required
     - Optional
   * - ``"memory"``
     - In-memory dictionary
       (:class:`~fleche.storage.ValueMemory` / :class:`~fleche.storage.CallMemory`)
     - —
     - ``remaining_depth`` *(value only)*
   * - ``"void"``
     - No-op; discards all data
       (:class:`~fleche.storage.ValueVoid` / :class:`~fleche.storage.CallVoid`)
     - —
     - —
   * - ``"pickle"``
     - Filesystem backend, standard ``pickle``
       (:class:`~fleche.storage.ValuePickleFile` / :class:`~fleche.storage.CallPickleFile`)
     - ``root``
     - ``compress``,
       ``secret_key``, ``remaining_depth`` *(value only)*
   * - ``"cloudpickle"``
     - Filesystem backend, ``cloudpickle``; handles lambdas, closures, etc.
       (same classes as ``"pickle"``)
     - ``root``
     - same as ``"pickle"``
   * - ``"dill"``
     - Filesystem backend, ``dill``
       (same classes as ``"pickle"``)
     - ``root``
     - same as ``"pickle"``
   * - ``"bagofholding_hdf"``
     - HDF5 files via ``bagofholding``
       (:class:`~fleche.storage.ValueBagOfHoldingH5File` /
       :class:`~fleche.storage.CallBagOfHoldingH5File`)
     - ``root``
     - ``lock_timeout``,
       ``version_validator``, ``prefix_length``, ``remaining_depth`` *(value only)*
   * - ``"sql"``
     - SQL via SQLAlchemy (:class:`~fleche.storage.Sql`).
       *Call storage only.*
     - —
     - ``url``, ``echo``

Key descriptions
^^^^^^^^^^^^^^^^

``root``
    Path to the storage directory (string; ``~`` is expanded).

``compress``
    (bool, default ``false``) — gzip-compress each stored file.

``lock_timeout``
    (float, default ``1.0``) — maximum seconds to wait to acquire a file lock
    (``"bagofholding_hdf"`` only; locks guard its shared multi-bag files, so
    per-key mode ``prefix_length = 0`` writes atomically without locks).  On
    reads, if the timeout expires the lock is skipped and the read proceeds
    with a ``WARNING`` logged.  On writes, if the timeout expires
    ``filelock.Timeout`` is raised.  The pickle-family
    backends write atomically and use no file locks; configs that still carry
    the key there load fine, but it is dropped with a ``FutureWarning``
    (deprecated).

``secret_key``
    (list of hex strings) — HMAC-SHA256 signing keys for tamper detection;
    see :doc:`security` for details.  If omitted, falls back to the
    ``FLECHE_SECRET_KEY`` environment variable.

``url``
    (str, default ``"sqlite:///:memory:"``) — SQLAlchemy connection URL, e.g.
    ``"sqlite:///~/.cache/fleche/calls.db"``. Leading ``~`` is expanded to the
    home directory in ``sqlite:///`` URLs. This default is **not** persistent
    — history vanishes when the process exits. It only applies to a bare
    ``calls.type = "sql"`` block; the ``sql`` :ref:`template <cache-templates>`
    below defaults ``url`` to the persistent ``sqlite:///root/calls.db``
    instead.

``echo``
    (bool, default ``false``) — log all SQL statements to stderr (useful for
    debugging).

``version_validator``
    (str, default omitted) — version validation strategy passed to
    ``bagofholding``'s ``H5Bag.load``.  One of ``"exact"``,
    ``"semantic-minor"``, ``"semantic-major"``, or ``"none"``.  When omitted,
    ``bagofholding``'s own default applies.

``prefix_length``
    (int, default ``2``) — *``bagofholding_hdf`` only.*  Multiplexes keys
    into shared HDF5 files instead of one file per key; ``0`` keeps one file
    per key, ``None`` infers the length from the files already in ``root``.
    See `Multi-bagging (bagofholding_hdf)`_ below.

``remaining_depth``
    (int, default ``1``) — destructuring depth; see `Destructuring`_ below.

Multi-bagging (``bagofholding_hdf``)
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

With ``prefix_length = 0``, ``"bagofholding_hdf"`` writes one ``.h5``
file per cache key — fine for a handful of large arrays, but a lot of small
files if you cache many small results, since every file carries HDF5's fixed
per-file overhead and each ``put``/``get`` opens and closes its own file.

Setting ``prefix_length`` groups keys that share the first *N* characters of
their digest into a single file at ``root/{key[:N]}.h5``, storing each key as
a sibling HDF5 group inside it (named by the full key) rather than as its own
file.  This trades a bit of write contention on the shared file (each
``put``/``get``/``evict`` still takes a per-file lock) for far fewer files on
disk. It's a single fixed split — there's no adaptive re-splitting as a
prefix bucket grows.

.. code-block:: toml

   [hdf5_multi]
   values.type = "bagofholding_hdf"
   values.root = "~/.cache/fleche/hdf5_values"
   values.prefix_length = 3   # spread keys across up to 4096 *.h5 files
   calls.type = "sql"
   calls.url = "sqlite:///~/.cache/fleche/calls.db"

Since digests are SHA256 hex strings, the default ``prefix_length = 2``
spreads keys across up to 256 files (``"00.h5"`` .. ``"ff.h5"``); among
grouping lengths of 1 and up, a smaller value groups more keys per file
(fewer files, more contention per file) and a larger value groups fewer.
``0`` is not the smallest grouping length but a special case that disables
multi-bagging entirely, reverting to one file per key — the opposite
extreme from grouping. Digests are already uniformly distributed, so bucket
sizes stay roughly even without any extra bookkeeping. Set it to ``None``
(only possible when constructing the backend from Python — TOML cannot
express ``None``) to infer the length from the files already in ``root``,
falling back to the default on an empty root.

``prefix_length`` is checked against the files already present in ``root``
when the storage is constructed: opening an existing cache directory with a
different ``prefix_length`` raises a ``ValueError`` instead of silently
leaving the old entries unreachable.  To re-shard an existing cache, open it
with its current ``prefix_length`` and call
:meth:`~fleche.storage.bagofholding_file.BagOfHoldingH5FileBackend.refix`
with the new length (``0`` for per-key), which moves every stored entry into
the new layout and returns a storage addressing it (the original instance is
left untouched and sees the drained old layout).  A root left with *several*
layouts — e.g. by an interrupted ``refix`` — cannot be opened normally;
repair it with
:meth:`~fleche.storage.bagofholding_file.BagOfHoldingH5FileBackend.consolidate`,
which migrates every prefix length it finds to a target length and returns
the resulting storage.

.. _configuring-destructuring:

Destructuring
^^^^^^^^^^^^^

Most value backends (``"memory"``, ``"pickle"``, ``"cloudpickle"``,
``"dill"``, ``"bagofholding_hdf"``) store collections (:class:`list`,
:class:`tuple`, :class:`dict`) by *destructuring* them: each element is stored
independently under its own cache key, and on load the original structure is
reassembled.  This avoids redundant storage of shared sub-structures across
different cached calls.  See :doc:`destructuring` for a full discussion with
figures, including the special cases (opaque objects, namedtuples, empty
containers).

The optional ``remaining_depth`` key (integer, default ``1``) controls the
granularity — see :doc:`destructuring` for the full depth rule, with figures.
In short: ``0`` splits every element into its own entry; the default ``1``
inlines scalars into their parent so a flat list or dict of scalars becomes a
single entry; higher values inline progressively deeper sub-collections too,
trading storage entries and structural sharing for fewer, larger entries.

Example:

.. code-block:: toml

   [mycache]
   values.type = "cloudpickle"
   values.root = "~/.cache/fleche/values"
   values.remaining_depth = 0   # split every element into its own entry
   calls.type = "cloudpickle"
   calls.root = "~/.cache/fleche/calls"

Cache type
~~~~~~~~~~

The cache type is selected **implicitly** from the shape of the section.
The default is a plain :class:`~fleche.caches.Cache`; additional top-level
keys turn the section into a wrapper or specialised variant.

``read_only``
^^^^^^^^^^^^^

(bool, default ``false``) — wrap the section in a
:class:`~fleche.caches.ReadOnlyCache`.  Loads continue to work, but saving
or evicting raises :class:`~fleche.caches.Rejected`.  Useful for pinning a
shared, immutable cache that should never be modified from the local
process.

.. code-block:: toml

   [readonly]
   values.type = "cloudpickle"
   values.root = "~/.cache/fleche/values"
   calls.type = "cloudpickle"
   calls.root = "~/.cache/fleche/calls"
   read_only = true

``max_size``
^^^^^^^^^^^^

(int, optional) — turn the section into a
:class:`~fleche.caches.SizeLimitedCache` that keeps at most ``max_size``
call records.  When the limit is exceeded a record is randomly selected for
eviction.  Value storage is not pruned.

.. code-block:: toml

   [limited]
   values.type = "memory"
   calls.type = "memory"
   max_size = 100

``read_only`` and ``max_size`` can be combined; the resulting cache is a
``ReadOnlyCache`` wrapping a ``SizeLimitedCache``.

CacheStack via array-of-tables
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

A TOML *array of tables* (``[[name]]``) defines a
:class:`~fleche.caches.CacheStack`.  Each element is configured exactly
like a normal cache section (including ``read_only`` / ``max_size``).
The first element is the base cache (saves go here; fallback hits are
back-filled into it); subsequent elements are the fallback layers,
checked in order.  See :doc:`cache_stack` for the runtime behaviour.

.. code-block:: toml

   # Saves go to the first layer; loads fall through to the second,
   # and hits there are copied back into the first.
   [[mystack]]
   values.type = "memory"
   calls.type = "memory"

   [[mystack]]
   values.type = "cloudpickle"
   values.root = "~/.cache/fleche/values"
   calls.type = "cloudpickle"
   calls.root = "~/.cache/fleche/calls"

CachePool via a ``pool`` array-of-tables
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

A dict section with a ``pool`` key (itself an array of tables,
``[[name.pool]]``) defines a :class:`~fleche.caches.CachePool`: a
**read-only, unordered collection** of caches queried as one.  Each member
is configured like a normal cache section (including ``read_only`` /
``max_size`` or even a nested stack).

Unlike a ``CacheStack``, a pool never writes to any member: ``save`` and
``evict`` raise :class:`~fleche.caches.Rejected`, and a ``load`` hit is
**not** back-filled anywhere.  Reads fan out across all members —
``contains`` is true if any member holds the key, ``query`` returns the
deduplicated union, and ``load`` returns the first member that holds the
key.  Use it to expose several independent, immutable caches (a teammate's
results directory, a shared archive, last month's run) as one cache you can
read from without risking a write to any of them.

.. code-block:: toml

   # A read-only pool over two independent on-disk caches.
   [[shared.pool]]
   values.type = "cloudpickle"
   values.root = "~/.cache/fleche/values"
   calls.type = "cloudpickle"
   calls.root = "~/.cache/fleche/calls"

   [[shared.pool]]
   values.type = "cloudpickle"
   values.root = "/shared/teammate/.cache/fleche/values"
   calls.type = "cloudpickle"
   calls.root = "/shared/teammate/.cache/fleche/calls"

Full Configuration Example
--------------------------

Below is an example of a complete configuration file demonstrating several features:

.. code-block:: toml

   [default]
   cache = "persistent"
   metadata = ["Runtime"]

   [persistent]
   # Store values as cloudpickle files
   values.type = "cloudpickle"
   values.root = "~/.cache/fleche/values"

   # Store call details as cloudpickle files
   calls.type = "cloudpickle"
   calls.root = "~/.cache/fleche/calls"

   [fast]
   # Simple in-memory cache
   values.type = "memory"
   calls.type = "memory"

   [hdf5_values]
   # HDF5 values backend with SQL call index
   values.type = "bagofholding_hdf"
   values.root = "~/.cache/fleche/hdf5_values"
   calls.type = "sql"
   calls.url = "sqlite:///~/.cache/fleche/calls.db"

   # Size-limited in-memory cache (evicts random call records past 100)
   [limited]
   values.type = "memory"
   calls.type = "memory"
   max_size = 100

   # Read-only view of a shared on-disk cache
   [readonly]
   values.type = "cloudpickle"
   values.root = "~/.cache/fleche/values"
   calls.type = "cloudpickle"
   calls.root = "~/.cache/fleche/calls"
   read_only = true

   # CacheStack: fast in-memory layer in front of a persistent layer
   [[layered]]
   values.type = "memory"
   calls.type = "memory"

   [[layered]]
   values.type = "cloudpickle"
   values.root = "~/.cache/fleche/values"
   calls.type = "cloudpickle"
   calls.root = "~/.cache/fleche/calls"

   # CachePool: a read-only collection of two independent caches
   [[shared.pool]]
   values.type = "cloudpickle"
   values.root = "~/.cache/fleche/values"
   calls.type = "cloudpickle"
   calls.root = "~/.cache/fleche/calls"

   [[shared.pool]]
   values.type = "cloudpickle"
   values.root = "/shared/team/.cache/fleche/values"
   calls.type = "cloudpickle"
   calls.root = "/shared/team/.cache/fleche/calls"
