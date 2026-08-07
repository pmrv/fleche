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
  - **Thread-safe** – ``ContextVar``-based state management

* **Get started** – see the :doc:`installation`.

.. toctree::
   :maxdepth: 2
   :caption: Getting Started

   installation

.. toctree::
   :maxdepth: 2
   :caption: Using Fleche

   usage/tldr
   usage/purity
   usage/helpers
   usage/file_semantics
   usage/lazy_call
   usage/query

.. toctree::
   :maxdepth: 2
   :caption: Recipes

   recipes/files_and_paths

.. toctree::
   :maxdepth: 2
   :caption: Digests

   digests/digests_as_args
   digests/digest_equivalence
   digests/entry_points

.. toctree::
   :maxdepth: 2
   :caption: Caches & Storage

   storage/configuration
   storage/cache_stack
   storage/security

.. toctree::
   :maxdepth: 2
   :caption: Advanced

   parallel_execution

.. toctree::
   :maxdepth: 2
   :caption: Development

   dev/custom_digests
   dev/path_storage
   dev/developer
   dev/ssh_cache

.. toctree::
   :maxdepth: 1
   :caption: Notebooks

   notebooks/GettingStarted
   notebooks/ExtraMethods
   notebooks/StorageBackends
   notebooks/SecureStorage
   notebooks/Caches
   notebooks/CacheStack
   notebooks/TransferWorkflow
   notebooks/ConcurrentExecution
   notebooks/Files
   notebooks/PathsInContainers

.. toctree::
   :maxdepth: 2
   :caption: API Reference

   autoapi/fleche/index

Indices and tables
==================

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`
