CacheStack
==========

A ``CacheStack`` allows combining multiple caches into a single prioritized hierarchy.
It is a common pattern to combine a fast, local cache (like an in-memory cache) with a
larger, slower, and potentially remote cache (like a database or file system).

Behavior
--------

* **Saving**: When saving a result, it is always written to the **first** cache in the stack.
* **Loading**: When loading a result, the stack is traversed from top to bottom (in the order caches were provided).
* **Automatic Hit Transfer**: If a result is found in a higher-level cache (index > 0), it is automatically transferred to the base cache (index 0). This ensures that frequently accessed data migrates to the fastest cache in your stack.

Example
-------

.. code-block:: python

    from fleche import fleche, cache
    from fleche.caches import Cache, CacheStack
    from fleche.storage import Memory

    # Define two caches
    local_cache = Cache(Memory({}), Memory({}))
    remote_cache = Cache(Memory({}), Memory({}))

    # Create a stack
    stack = CacheStack((local_cache, remote_cache))

    @fleche
    def my_function(x):
        return x * 2

    with cache(stack):
        # Result is found in remote_cache, and automatically saved to local_cache
        my_function(10)

Automatic hit transfer only applies to full function calls (``Call`` objects) and not to individual values loaded via ``load_value``.
