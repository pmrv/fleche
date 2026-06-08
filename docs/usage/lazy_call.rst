Lazy Loading
============

In many caching scenarios, function results or arguments can be large objects (e.g., massive datasets, trained models, or high-resolution images). Loading all of them from the cache every time you inspect a call would be expensive and slow.

Fleche avoids this by returning **lazy call objects** from ``load()`` and ``query()`` by default. Arguments and results are only fetched from the underlying storage when you actually access them.

What is a LazyCall?
-------------------

When you call ``cache().load(key)`` or iterate over ``cache().query(...)``, you get back a ``LazyCall`` rather than a full ``Call``. A ``LazyCall`` holds the digests (unique identifiers) of the arguments and result, plus a reference to the cache, but none of the actual Python objects. Those are loaded from storage on demand whenever you access them.

.. code-block:: python

   from fleche import cache

   # Default: returns a LazyCall — cheap, no deserialization yet
   lazy_call = cache().load(key)

   # Arguments and results are fetched only when accessed
   print(lazy_call.result)          # Triggers a load from value storage
   print(lazy_call.arguments['x'])  # Triggers a load for argument 'x'

To load everything upfront, call ``.fetch()`` on an existing ``LazyCall``:

.. code-block:: python

   # Fetch everything from a lazy call you already have
   call = lazy_call.fetch()

Parity with Call
----------------

``LazyCall`` is a drop-in stand-in for ``Call``:

* **Digests**: ``digest(lazy_call)`` is identical to ``digest(original_call)``.
* **Lookup Keys**: ``lazy_call.to_lookup_key()`` returns the same key.
* **Immutability**: ``LazyCall`` is a frozen dataclass — its fields cannot be reassigned after creation.

LazyArguments
-------------

The ``arguments`` attribute of a ``LazyCall`` returns a ``LazyArguments`` proxy. This proxy implements the standard Python ``Mapping`` interface, so you can use it like a regular dictionary. Each argument is fetched from storage on each access by key — there is no per-key caching inside the proxy itself.

When lazy loading helps most
-----------------------------

1. **Browsing large caches**: When iterating over many calls via ``query()``, you can inspect names, digests, and metadata without deserializing any results.
2. **Existence checks**: ``contains()`` uses lazy loading internally — it never deserializes a result just to confirm something is cached.
3. **Selective access**: When you only need one or two arguments out of a call that stores many large objects.
