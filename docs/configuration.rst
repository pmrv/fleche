Configuration
=============

``fleche`` looks for a configuration file in the following order:

1. ``fleche.toml`` in the current working directory (local config)
2. A global config file, determined by the first matching rule:

   - If ``$XDG_CONFIG_HOME`` is set: ``$XDG_CONFIG_HOME/fleche/cache.toml``
   - Otherwise, if ``$HOME`` is set: ``$HOME/.fleche.toml``
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

``"memory"``
    Stores data in an in-memory dictionary
    (:class:`~fleche.storage.ValueMemory` / :class:`~fleche.storage.CallMemory`).
    No extra keys.

``"void"``
    No-op backend — discards all data
    (:class:`~fleche.storage.ValueVoid` / :class:`~fleche.storage.CallVoid`).
    No extra keys.

``"pickle"``
    Stores data as files on the filesystem using the standard ``pickle`` module
    (:class:`~fleche.storage.ValuePickleFile` / :class:`~fleche.storage.CallPickleFile`).
    Required: ``root`` — path to the storage directory.

``"cloudpickle"``
    Same filesystem backend as ``"pickle"``, but serialised with ``cloudpickle``.
    Handles more complex Python objects (lambdas, closures, etc.).
    Required: ``root``.

``"dill"``
    Same filesystem backend as ``"pickle"``, but serialised with ``dill``.
    Required: ``root``.

``"bagofholding_hdf"``
    Stores data in HDF5 files using the ``bagofholding`` library
    (:class:`~fleche.storage.ValueBagOfHoldingH5File` /
    :class:`~fleche.storage.CallBagOfHoldingH5File`).
    Required: ``root``.

``"sql"``
    Stores call metadata in a SQL database via SQLAlchemy
    (:class:`~fleche.storage.Sql`).
    Intended for **call storage only**.
    Required: ``url`` — a SQLAlchemy connection URL, e.g.
    ``"sqlite:///~/.fleche/calls.db"``.

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
