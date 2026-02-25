Lazy Loading with LazyCall
==========================

In many caching scenarios, function results or arguments can be large objects (e.g., massive datasets, trained models, or high-resolution images). Loading these objects from the cache every time you inspect a call can be expensive and slow.

To address this, Fleche provides a **lazy loading** mechanism via the ``LazyCall`` class.

What is LazyCall?
----------------

A ``LazyCall`` is a lightweight sibling to the standard ``Call`` object. Instead of holding the actual Python objects for arguments and results, it holds their **digests** (unique identifiers) and a reference to the cache.

The actual data is only loaded from the underlying storage when you explicitly access it.

Using Lazy Loading
------------------

You can request lazy loading by passing ``lazy=True`` to the ``load()`` or ``query()`` methods of a cache.

.. code-block:: python

   from fleche import cache

   # Normal load: loads everything into memory
   call = cache().load(key, lazy=False)
   print(call.result)  # Already loaded

   # Lazy load: loads only metadata and digests
   lazy_call = cache().load(key, lazy=True)

   # Arguments and results are fetched only when accessed
   print(lazy_call.result)  # Triggers a load from value storage
   print(lazy_call.arguments['x'])  # Triggers a load for argument 'x'

Parity with Call
----------------

Despite being "lazy", ``LazyCall`` maintains full parity with ``Call``:

* **Digests**: ``digest(lazy_call)`` is identical to ``digest(original_call)``.
* **Lookup Keys**: ``lazy_call.to_lookup_key()`` returns the same key as the non-lazy version.
* **Immutability**: Like ``Call``, ``LazyCall`` is a frozen dataclass.

LazyArguments
-------------

The ``arguments`` attribute of a ``LazyCall`` returns a ``LazyArguments`` proxy. This proxy implements the standard Python ``Mapping`` interface, allowing you to use it like a dictionary while benefiting from lazy retrieval of individual arguments.

Performance Benefits
--------------------

Lazy loading is particularly beneficial when:

1. **Browsing Cache**: You are iterating over many calls (e.g., via ``query()``) and only need to inspect metadata or specific arguments.
2. **Existence Checks**: The ``contains()`` method in Fleche uses lazy loading internally to check for a call's existence without deserializing its result.
3. **Large Objects**: Your cache contains large data structures that are not always needed.
