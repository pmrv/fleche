CacheStack
==========

A ``CacheStack`` allows combining multiple caches into a single prioritized hierarchy.
It is a common pattern to combine a fast, local cache (like an in-memory cache) with a
larger, slower, and potentially remote cache (like a database or file system).

Behavior
--------

* **Saving**: When saving a result, it is always written to the **first** cache in the stack.
* **Loading**: When loading a result, the stack is traversed starting from the base cache (index 0) through each fallback cache in order.
* **Automatic Hit Transfer**: If a result is found in a fallback cache (index > 0), it is automatically copied down to the base cache (index 0). This ensures that frequently accessed data migrates to the fastest cache in your stack.

Example
-------

.. code-block:: python

    from fleche import fleche, cache
    from fleche.caches import Cache, CacheStack
    from fleche.storage import ValueMemory, CallMemory

    # Define two caches
    local_cache = Cache(ValueMemory({}), CallMemory({}))
    remote_cache = Cache(ValueMemory({}), CallMemory({}))

    @fleche
    def my_function(x):
        return x * 2

    # Populate remote_cache with a result
    with cache(remote_cache):
        my_function(10)

    # Create a stack: local_cache is the base cache (checked first), remote_cache is the fallback
    stack = CacheStack((local_cache, remote_cache))

    with cache(stack):
        # Result is found in remote_cache and automatically copied to local_cache
        my_function(10)

Automatic hit transfer only applies to full function calls (``Call`` objects) and not to individual values loaded via ``load_value``.
