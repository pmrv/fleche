CacheStack
==========

A ``CacheStack`` allows combining multiple caches into a single prioritized hierarchy.
It is a common pattern to combine a fast, local cache (like an in-memory cache) with a
larger, slower, and potentially remote cache (like a database or file system).

Behavior
--------

* **Saving**: When saving a result, it is always written to the **first** cache in the stack.
* **Loading**: When loading a result, the stack is traversed starting from the base cache (index 0) through each fallback cache in order.
* **Automatic Hit Transfer**: If a result is found in a fallback cache (index > 0), it is automatically copied down to the base cache (index 0). This ensures that frequently accessed data migrates to the fastest cache in your stack. This only applies to full function calls (``Call`` objects) — not to individual values loaded via ``load_value``.

Example
-------

.. code-block:: pycon

    >>> from fleche import fleche, cache
    >>> from fleche.caches import Cache, CacheStack
    >>> from fleche.storage import ValueMemory, CallMemory

    >>> # Define two caches
    >>> local_cache = Cache(ValueMemory({}), CallMemory({}))
    >>> remote_cache = Cache(ValueMemory({}), CallMemory({}))

    >>> @fleche
    ... def my_function(x):
    ...     return x * 2

    >>> # Populate remote_cache with a result
    >>> with cache(remote_cache):
    ...     my_function(10)

    >>> # Create a stack: local_cache is the base cache (checked first), remote_cache is the fallback
    >>> stack = CacheStack((local_cache, remote_cache))

    >>> with cache(stack):
    ...     # Result is found in remote_cache and automatically copied to local_cache
    ...     my_function(10)

Layering Caches at Runtime
---------------------------

Rather than constructing a ``CacheStack`` by hand, you can push a new cache on top of
whichever cache is currently active with :meth:`~fleche.caches.BaseCache.push`, or its
context-manager shortcut ``cache(new_cache, stack=True)``:

.. code-block:: pycon

    >>> from fleche import cache

    >>> cache(remote_cache);  # sticky: remote_cache becomes the active cache

    >>> with cache(local_cache, stack=True):
    ...     # local_cache is pushed on top: it is now stack[0] (checked and
    ...     # saved to first), remote_cache is the fallback.
    ...     ...
    >>> # remote_cache is restored on exit

``push`` always flattens rather than nests: pushing onto an existing ``CacheStack``
prepends the new cache to that stack's members instead of wrapping the whole stack, so
``stack=True`` never runs into the nesting restriction below.

Restrictions
------------

``CacheStack`` **cannot be nested**: passing a ``CacheStack`` as a member of
another ``CacheStack`` raises ``ValueError`` immediately::

   inner = CacheStack((cache_a, cache_b))
   outer = CacheStack((inner, cache_c))  # raises ValueError

Flatten the layers directly instead::

   flat = CacheStack((cache_a, cache_b, cache_c))

Or build up the same flattened stack with chained ``push`` calls, which is handy when
each cache becomes available one at a time::

   flat = cache_c.push(cache_b).push(cache_a)  # CacheStack((cache_a, cache_b, cache_c))
