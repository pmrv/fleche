Decorator Helpers
=================

Functions decorated with ``@fleche`` are enhanced with several helper methods that allow for manual interaction with the cache and inspection of function calls.

Helper Methods
--------------

The following methods are added to the decorated function:

``.call(*args, **kwargs)``
~~~~~~~~~~~~~~~~~~~~~~~~~~

Returns a ``Call`` object corresponding to the provided arguments. This object contains metadata about the call, such as the function name, arguments, and version, but does not execute the function.

``.digest(*args, **kwargs)``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Returns the unique cache key (a digest string) that would be used for the given call.

``.load(*args, **kwargs)``
~~~~~~~~~~~~~~~~~~~~~~~~~~

Attempts to load the result of a specific call from the cache. If the result is not cached, it raises a ``KeyError``.

``.contains(*args, **kwargs)``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Returns ``True`` if the result for the given call is already present in the cache, ``False`` otherwise.

Accessing the Original Function
-------------------------------

The original, undecorated function is always accessible via the ``.__wrapped__`` attribute. This is useful if you need to bypass the cache entirely for a specific call.

.. code-block:: python

   @fleche
   def my_func(x):
       return x * 2

   # Bypass cache
   result = my_func.__wrapped__(10)
