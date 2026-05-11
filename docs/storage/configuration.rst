Configuration
=============

``fleche`` looks for a configuration file in the following order:

1. ``fleche.toml`` in the current working directory (local config)
2. A global config file:

   - If ``$XDG_CONFIG_HOME`` is set: ``$XDG_CONFIG_HOME/fleche/cache.toml``
   - Otherwise: ``~/.fleche.toml``

The first file found is used. If no configuration file exists, ``fleche`` falls back to a default in-memory cache.

Reserved Cache Names
--------------------

``memory``
~~~~~~~~~~

The name ``memory`` is a reserved cache name. When requested, ``fleche`` will provide a transient in-memory cache. This cache is persistent for the duration of the process, but is not shared with other processes and is lost when the current process exits.

Example:

.. code-block:: python

   from fleche import cache
   with cache("memory"):
       # Results will be cached in memory. The cache persists for the lifetime of the process.
       ...

``void``
~~~~~~~~

The name ``void`` is a reserved cache name. When requested, ``fleche`` will provide a no-op cache that discards all stored values. This is useful for disabling caching entirely without changing your code.

Example:

.. code-block:: python

   from fleche import cache
   with cache("void"):
       # Results will not be cached at all. Every call executes the function.
       ...

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

The ``metadata`` key specifies the default metadata chain to use. This is a list of strings, where each string is the name of a metadata class from the ``fleche.metadata`` module.

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

All persistent value backends (``"memory"``, ``"pickle"``, ``"cloudpickle"``,
``"dill"``, ``"bagofholding_hdf"``) store collections (:class:`list`,
:class:`tuple`, :class:`dict`) by *destructuring* them: each element is stored
independently under its own cache key, and on load the original structure is
reassembled.  This avoids redundant storage of shared sub-structures across
different cached calls.  The ``"void"`` backend discards everything and performs
no splitting.

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
