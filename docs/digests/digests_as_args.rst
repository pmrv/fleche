Digests as Arguments
====================

`fleche` supports passing `Digest` objects as arguments to functions. When a `Digest` is passed as a top-level argument (either positional or keyword), `fleche` automatically looks up the corresponding value in the **value storage** and passes the resolved value to the decorated function.

This allows for efficient chaining of cached functions where intermediate results can be referenced by their value digest rather than held in memory.

Usage
-----

You can use the convenience wrapper ``D`` to mark a string as a value digest:

.. code-block:: python

    from fleche import fleche, D
    from fleche.digest import digest

    @fleche
    def func_a(x):
        return x + 1

    @fleche
    def func_b(y):
        return y * 2

    result_a = func_a(5)  # returns 6, stores it in value storage

    # The digest of the stored *value* (not the call lookup key)
    value_digest = digest(result_a)

    # Pass the value digest to func_b — it loads 6 from the cache
    result_b = func_b(D(value_digest))
    assert result_b == 12

Note the distinction between a **call lookup key** (returned by ``func.digest()``) and a **value digest** (the SHA256 of the Python object itself, obtained via ``fleche.digest.digest()``). ``D()`` works with value digests because it resolves arguments through the value storage.

Behavior
--------

- **Automatic Expansion**: Only immediate `Digest` arguments are expanded.
- **Non-recursive**: If you pass a list of digests like `[D(a), D(b)]`, the list will be passed as-is to the function, and the digests inside it will NOT be expanded.
- **Missing Digests**: If a `Digest` is passed but its value cannot be found in the current cache, a `KeyError` will be raised.
- **Short Digests**: If the underlying storage supports short-hand digest expansion, you can pass a short digest (at least 4 characters) to `D()`, and it will be expanded to the full value.

The `D` Wrapper
---------------

.. autofunction:: fleche.D
