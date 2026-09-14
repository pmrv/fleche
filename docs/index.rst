Fleche Documentation
====================

Welcome to the **Fleche** library documentation.

* **What is Fleche?**  A persistent caching library for Python functions — like
  ``lru_cache`` but persisted across runs. The ``@fleche()`` decorator wraps
  functions, generates content-based cache keys via SHA256 hashing, and stores
  results in configurable backends (file, SQL, memory, HDF5).

* **Key features**

  - **Persistent caching** – results survive process restarts
  - **Flexible storage backends** – filesystem, SQL, in-memory, and HDF5
  - **Intelligent hashing** – content-based SHA256 keys with type-aware support
    for numpy, pandas, and custom types
  - **Query support** – search and inspect cached calls as pandas DataFrames
  - **Configurable** – TOML-based project and global configuration
  - **Thread-safe active cache** – ``ContextVar``-based state management (see
    :doc:`parallel_execution` for concurrency caveats)

* **Get started** – see the :doc:`installation`.

.. toctree::
   :maxdepth: 2
   :caption: Getting Started
   :hidden:

   installation

.. toctree::
   :maxdepth: 2
   :caption: Using Fleche
   :hidden:

   usage/tldr
   usage/helpers
   usage/lazy_call
   usage/query

.. toctree::
   :maxdepth: 2
   :caption: Digests
   :hidden:

   digests/digests_as_args
   digests/digest_equivalence
   digests/entry_points

.. toctree::
   :maxdepth: 2
   :caption: Caches & Storage
   :hidden:

   storage/configuration
   storage/destructuring
   storage/cache_stack
   storage/security

.. toctree::
   :maxdepth: 2
   :caption: Advanced
   :hidden:

   parallel_execution

.. toctree::
   :maxdepth: 2
   :caption: Development
   :hidden:

   dev/call_lifecycle
   dev/custom_digests
   dev/extending_destructurer
   dev/function_profile
   dev/ssh_cache
   dev/sql_test_backends
   dev/storage_hierarchy

.. toctree::
   :maxdepth: 1
   :caption: Notebooks
   :hidden:

   notebooks/FiveMinuteTour
   notebooks/GettingStarted
   notebooks/ExtraMethods
   notebooks/StorageBackends
   notebooks/Destructuring
   notebooks/SecureStorage
   notebooks/Caches
   notebooks/CacheStack
   notebooks/TransferWorkflow
   notebooks/ConcurrentExecution

.. toctree::
   :maxdepth: 2
   :caption: API Reference
   :hidden:

   autoapi/fleche/index

Indices and tables
==================

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`
