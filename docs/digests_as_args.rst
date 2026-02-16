Digests as Arguments
====================

`fleche` supports passing `Digest` objects as arguments to functions. When a `Digest` is passed as a top-level argument (either positional or keyword), `fleche` automatically expands it to its cached value before calling the decorated function.

This allows for efficient chaining of cached functions where you don't need to load the full result into memory if you're just going to pass it to another cached function.

Usage
-----

You can use the convenience wrapper `D` to mark a string as a digest:

.. code-block:: python

    from fleche import fleche, D

    @fleche
    def func_a(x):
        return x + 1

    @fleche
    def func_b(y):
        return y * 2

    # Get the digest of the result of func_a(5)
    print(func_a.digest(5))
    # '6511a915535857f7e7ca73b8b62968975f357664ed331c38f9e188fa738223ad'

    # Pass it to func_b. func_b will receive the value 6, not the digest string.
    # You can even use a short digest!
    result = func_b(D('6511a915'))
    assert result == 12

Behavior
--------

- **Automatic Expansion**: Only immediate `Digest` arguments are expanded.
- **Non-recursive**: If you pass a list of digests like `[D(a), D(b)]`, the list will be passed as-is to the function, and the digests inside it will NOT be expanded.
- **Missing Digests**: If a `Digest` is passed but its value cannot be found in the current cache, a `KeyError` will be raised.
- **Short Digests**: If the underlying storage supports short-hand digest expansion, you can pass a short digest (at least 4 characters) to `D()`, and it will be expanded to the full value.

The `D` Wrapper
---------------

.. autofunction:: fleche.D
