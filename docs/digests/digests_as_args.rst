Digests as Arguments
====================

``fleche`` supports passing ``Digest`` objects as arguments to functions. When a ``Digest`` is passed as an immediate argument (either positional or keyword), ``fleche`` automatically looks up the corresponding value in the **value storage** and passes the resolved value to the decorated function.

This allows for efficient chaining of cached functions where intermediate results can be referenced by their value digest rather than held in memory.

Usage
-----

You can use the convenience wrapper ``D`` to mark a string as a value digest:

.. code-block:: pycon

    >>> from fleche import fleche, D
    >>> from fleche.digest import digest

    >>> @fleche
    ... def func_a(x):
    ...     return x + 1

    >>> @fleche
    ... def func_b(y):
    ...     return y * 2

    >>> result_a = func_a(5)  # returns 6, stores it in value storage

    >>> # The digest of the stored *value* (not the call lookup key)
    >>> value_digest = digest(result_a)

    >>> # Pass the value digest to func_b — it loads 6 from the cache
    >>> result_b = func_b(D(value_digest))
    >>> assert result_b == 12

Note the distinction between a **call lookup key** (returned by ``func.digest(*args, **kwargs)``) and a **value digest** (the SHA256 of the Python object itself, obtained via ``fleche.digest.digest()``). ``D()`` works with value digests because it resolves arguments through the value storage.

Behavior
--------

- **Automatic Expansion**: Only immediate ``Digest`` arguments are expanded.
- **Non-recursive**: If you pass a list of digests like ``[D(a), D(b)]``, the list will be passed as-is to the function, and the digests inside it will **not** be expanded.
- **Missing Digests**: If a ``Digest`` is passed but its value cannot be found in the current cache, a ``KeyError`` will be raised.
- **Short Digests**: If the underlying storage supports short-hand digest expansion, you can pass a short digest (at least 4 characters) to ``D()``, and it will be expanded to the full value.

Looking Up a Value Directly
----------------------------

``D()`` is also the ergonomic entry point for the opposite direction: given a value
you already hold, or a digest hex string copied from a log line or from
``cache().table()``, fetch the corresponding entry from the active cache's value
storage without importing ``fleche.digest.digest`` yourself.

- **You have the value itself.** ``D()`` computes its digest, which
  :meth:`~fleche.caches.BaseCache.load_value` accepts directly:

  .. code-block:: pycon

     >>> from fleche import fleche, cache, D

     >>> @fleche
     ... def compute(x):
     ...     return x * 2

     >>> with cache("memory"):
     ...     result = compute(21)                # populates the cache
     ...     assert cache().load_value(D(result)) == result

- **You have a digest hex string** (possibly shortened). ``D()`` recognises hex
  strings and wraps them into a :class:`~fleche.digest.Digest` instead of hashing
  them; call :meth:`~fleche.digest.Digest.expand` to resolve a short prefix back to
  the full digest before loading it:

  .. code-block:: pycon

     >>> with cache("memory"):
     ...     result = compute(21)
     ...     short = D(result).shrink()          # shortest unambiguous prefix
     ...     assert cache().load_value(D(short).expand()) == result

If you instead have the *original arguments* of a decorated call rather than its
result, prefer ``func.load(*args, **kwargs)`` (see :doc:`/usage/helpers`) — it
re-derives the lookup key from the arguments and needs no digest at all.

The ``D`` Wrapper
------------------

.. autofunction:: fleche.D
   :no-index:
