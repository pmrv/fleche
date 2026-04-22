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

``.query(*args, metadata={}, **kwargs)``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Returns matching cached calls from the active cache. Any argument passed as ``None`` acts as a wildcard, matching any stored value for that parameter. The ``metadata`` keyword argument accepts a dictionary of metadata tags to further filter results (e.g., ``metadata={"tags": {"project": "alpha"}}``).

See :doc:`query` for a detailed guide on querying cached calls.

``.rerun(*args, **kwargs)``
~~~~~~~~~~~~~~~~~~~~~~~~~~~

Forces the function to re-execute, even if its result is already present in the cache, and saves the newly computed result to the cache. This forces reevaluation recursively for any nested `@fleche` calls as well.

Accessing the Original Function
-------------------------------

The original, undecorated function is always accessible via the ``.__wrapped__`` attribute. This is useful if you need to bypass the cache entirely for a specific call.

.. code-block:: python

   @fleche
   def my_func(x):
       return x * 2

   # Bypass cache
   result = my_func.__wrapped__(10)

Usage with Decorated Methods
-----------------------------

.. note::

   When ``@fleche`` is applied to a method, the helper methods (`.call`, `.digest`, `.query`,
   `.load`, `.contains`, `.rerun`) do **not** automatically bind ``self``. Accessing
   ``obj.method.query`` returns the same unbound helper as ``MyClass.method.query`` — Python's
   descriptor protocol does not propagate through attribute lookups on bound methods.

   You must pass the instance explicitly as the first positional argument:

   .. code-block:: python

      class MyClass:
          @fleche
          def compute(self, x):
              ...

      obj = MyClass()

      # Correct — pass self explicitly
      obj.compute.query(obj, x=5)
      obj.compute.contains(obj, x=5)
      obj.compute.digest(obj, x=5)

      # Also works as a keyword argument
      obj.compute.query(self=obj, x=5)
