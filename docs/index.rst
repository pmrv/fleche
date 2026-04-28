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
   :caption: Contents:

   installation
   helpers
   cache_stack
   lazy_call
   digests_as_args
   digest_equivalence
   custom_digests
   configuration
   query
   parallel_execution
   security

.. toctree::
   :maxdepth: 1
   :caption: Notebooks:

   notebooks/GettingStarted
   notebooks/ExtraMethods
   notebooks/StorageBackends
   notebooks/SecureStorage
   notebooks/CacheStack
   notebooks/ConcurrentExecution

.. toctree::
   :maxdepth: 2
   :caption: API Reference:

   autoapi/fleche/index

Indices and tables
==================

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`
