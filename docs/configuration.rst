Configuration
=============

``fleche`` can be configured using a TOML file located at ``$XDG_CONFIG_HOME/fleche/cache.toml`` (or ``~/.config/fleche/cache.toml`` if ``$XDG_CONFIG_HOME`` is not set).

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
   metadata = ["Runtime", "CallInfo"]

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

You can also nest storage configurations. This is useful for creating complex storage backends, like a compressed storage that wraps another storage.

To configure a nested storage, you can use a ``inner`` key, which contains the configuration for the inner storage.

Example:

.. code-block:: toml

   [nested]
   values.type = "CompressedStorage"
   values.compression = "gzip"
   values.inner.type = "BagOfHoldingH5File"
   values.inner.root  = "..."
   calls.type = "CloudpickleFile"
   calls.root = "~/.fleche/calls"

Full Configuration Example
--------------------------

Below is an example of a complete configuration file demonstrating several features:

.. code-block:: toml

   [default]
   cache = "persistent"
   metadata = ["Runtime", "CallInfo"]

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

   [compressed]
   # Example of nested storage with compression
   values.type = "CompressedStorage"
   values.compression = "gzip"
   values.inner.type = "BagOfHoldingH5File"
   values.inner.root  = "~/.cache/fleche/compressed_values"
   calls.type = "CloudpickleFile"
   calls.root = "~/.cache/fleche/compressed_calls"
