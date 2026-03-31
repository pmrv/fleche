Configuration
=============

``fleche`` looks for a configuration file in the following order:

1. ``fleche.toml`` in the current working directory (local config)
2. ``$XDG_CONFIG_HOME/fleche/cache.toml`` (if ``$XDG_CONFIG_HOME`` is set)
3. ``$HOME/.fleche.toml`` (if ``$HOME`` is set)
4. ``~/.fleche.toml`` (fallback)

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

Each storage backend is configured using a ``type`` key, which specifies the name of the storage class from the ``fleche.storage`` module. Other keys are passed as arguments to the storage class constructor.

Example:

.. code-block:: toml

   [mycache]
   values.type = "Memory"
   calls.type = "Memory"

Available storage types
~~~~~~~~~~~~~~~~~~~~~~~

* :class:`~fleche.storage.Memory`: Stores data in an in-memory dictionary. It takes no arguments.
* :class:`~fleche.storage.PickleFile`: Stores data as files on the filesystem, using the standard ``pickle`` module for serialization. It takes a ``root`` argument, which is the path to the directory where the files will be stored.
* :class:`~fleche.storage.CloudpickleFile`: Stores data as files on the filesystem, using ``cloudpickle`` for serialization. It handles more complex Python objects than standard ``pickle``. It takes a ``root`` argument, which is the path to the directory where the files will be stored.
* :class:`~fleche.storage.DillFile`: Stores data as files on the filesystem, using ``dill`` for serialization. It takes a ``root`` argument, which is the path to the directory where the files will be stored.
* :class:`~fleche.storage.BagOfHoldingH5File`: Stores data in an HDF5 file using the ``bagofholding`` library. It takes a ``root`` argument, which is the path to the directory where the files will be stored.
* :class:`~fleche.storage.Sql`: Stores call metadata in a SQL database using SQLAlchemy. It is intended for use as a ``calls`` storage. It takes a ``url`` argument (e.g., ``sqlite:///calls.db``).

Nested storage
~~~~~~~~~~~~~~

You can also nest storage configurations. For example, :class:`~fleche.storage.DestructuringStorage` wraps another storage backend to recursively break down complex Python objects (lists, tuples, dicts) before storing them.

To configure a nested storage, use a ``storage`` sub-key containing the configuration for the inner storage.

Example:

.. code-block:: toml

   [nested]
   values.type = "DestructuringStorage"
   values.storage.type = "BagOfHoldingH5File"
   values.storage.root = "~/.fleche/nested_values"
   calls.type = "CloudpickleFile"
   calls.root = "~/.fleche/calls"

Full Configuration Example
--------------------------

Below is an example of a complete configuration file demonstrating several features:

.. code-block:: toml

   [default]
   cache = "persistent"
   metadata = ["Runtime"]

   [persistent]
   # Store values in HDF5 files
   values.type = "BagOfHoldingH5File"
   values.root = "~/.cache/fleche/values"

   # Store call details as cloudpickle files
   calls.type = "CloudpickleFile"
   calls.root = "~/.cache/fleche/calls"

   [fast]
   # Simple in-memory cache
   values.type = "Memory"
   calls.type = "Memory"

   [destructured]
   # Example of nested storage with destructuring
   values.type = "DestructuringStorage"
   values.storage.type = "BagOfHoldingH5File"
   values.storage.root = "~/.cache/fleche/destructured_values"
   calls.type = "CloudpickleFile"
   calls.root = "~/.cache/fleche/destructured_calls"
