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

If no configuration file is discovered, ``fleche`` falls back to a default
in-memory cache.

Reserved Cache Names
--------------------

``memory``
~~~~~~~~~~

The name ``memory`` is a reserved cache name. When requested, ``fleche`` will provide a transient in-memory cache. This cache is persistent for the duration of the process, but is not shared with other processes and is lost when the current process exits.

Example:

.. code-block:: pycon

   >>> from fleche import cache
   >>> with cache("memory"):
   ...     # Results will be cached in memory. The cache persists for the lifetime of the process.
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

Cache sections
--------------

You can define multiple cache configurations in the same file, each in its own section.

Each cache section must define two storage backends: ``values`` and ``calls``. ``values`` is used to store the results of function calls, and ``calls`` is used to store the function call details.

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
     - ``compress``, ``lock_timeout``,
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
       ``version_validator``, ``remaining_depth`` *(value only)*
   * - ``"sql"``
     - SQL via SQLAlchemy (:class:`~fleche.storage.Sql`).
       *Call storage only.*
     - ``url``
     - ``echo``

Key descriptions
^^^^^^^^^^^^^^^^

``root``
    Path to the storage directory (string; ``~`` is expanded).

``compress``
    (bool, default ``false``) — gzip-compress each stored file.

``lock_timeout``
    (float, default ``1.0``) — maximum seconds to wait for a concurrent write lock
    before attempting a read anyway.

``secret_key``
    (list of hex strings) — HMAC-SHA256 signing keys for tamper detection;
    see :doc:`security` for details.  If omitted, falls back to the
    ``FLECHE_SECRET_KEY`` environment variable.

``url``
    SQLAlchemy connection URL, e.g. ``"sqlite:///~/.cache/fleche/calls.db"``.
    Leading ``~`` is expanded to the home directory in ``sqlite:///`` URLs.

``echo``
    (bool, default ``false``) — log all SQL statements to stderr (useful for
    debugging).

``version_validator``
    (str, default omitted) — version validation strategy passed to
    ``bagofholding``'s ``H5Bag.load``.  One of ``"exact"``,
    ``"semantic-minor"``, ``"semantic-major"``, or ``"none"``.  When omitted,
    ``bagofholding``'s own default applies.

``remaining_depth``
    (int, default ``0``) — destructuring depth; see `Destructuring`_ below.

Destructuring
^^^^^^^^^^^^^

Most value backends (``"memory"``, ``"pickle"``, ``"cloudpickle"``,
``"dill"``, ``"bagofholding_hdf"``) store collections (:class:`list`,
:class:`tuple`, :class:`dict`) by *destructuring* them: each element is stored
independently under its own cache key, and on load the original structure is
reassembled.  This avoids redundant storage of shared sub-structures across
different cached calls.

The optional ``remaining_depth`` key (integer, default ``0``) controls the granularity:

* ``remaining_depth = 0`` — maximum splitting: every element at every nesting level is
  stored as a separate entry.
* ``remaining_depth = N`` (positive) — elements whose structural depth is less than *N*
  are stored inline within their parent entry rather than as separate entries.
  Depth is measured from the deepest scalar leaf: scalars (:class:`int`, :class:`str`,
  etc.) have depth 0; a container has depth ``1 + max(children depths)``.
  With ``remaining_depth = 1``, scalars (depth 0) are inlined into their parent
  container, so a flat list or dict of only scalars becomes a single cache entry.
  Nested sub-collections (depth ≥ 1) are still stored as separate entries.

Higher values mean fewer, larger storage entries and less structural sharing between calls.

Example:

.. code-block:: toml

   [mycache]
   values.type = "cloudpickle"
   values.root = "~/.cache/fleche/values"
   values.remaining_depth = 1   # inline scalars into their parent container
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
