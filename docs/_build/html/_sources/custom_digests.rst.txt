Customizing Digests
===================

``fleche`` uses digests to identify objects and determine if a cached result can be reused. By default, it supports many built-in Python types, numpy arrays, and dataclasses. For other types, or to customize how a digest is calculated, you can use one of the following methods.

The ``__digest__`` Method
-------------------------

The simplest way to customize the digest of an object is to implement a ``__digest__`` method on its class. This method should return a string representing the object's state.

.. code-block:: python

   class MyType:
       def __init__(self, value):
           self.value = value

       def __digest__(self):
           return f"MyType:{self.value}"

Using ``add_hook``
------------------

If you cannot or do not want to modify a class, you can register a custom digest function using ``fleche.digest.add_hook``.

.. code-block:: python

   from fleche.digest import add_hook, Hook

   class ExternalType:
       def __init__(self, data):
           self.data = data

   def external_digest(obj):
       return f"External:{obj.data}"

   add_hook(Hook(ExternalType, external_digest))
   # Or using a tuple
   # add_hook((ExternalType, external_digest))

Hooks registered this way have the highest priority and will override any other digest logic for the given type.

Registering Entry Points
------------------------

For library authors who want to provide ``fleche`` support for their types without requiring users to manually call ``add_hook``, ``fleche`` supports Python entry points.

You can register your digest hooks in the ``fleche.digest`` entry point group in your ``pyproject.toml`` (or equivalent).

.. code-block:: toml

   [project.entry-points."fleche.digest"]
   my_package_hooks = "my_package.hooks:get_hooks"

The entry point can point to:
* A single ``fleche.digest.Hook`` object.
* A tuple of ``(Type, Callable)``.
* A list containing any combination of the above.

.. code-block:: python

   # my_package/hooks.py
   from fleche.digest import Hook

   def get_hooks():
       return [
           Hook(TypeA, digest_a),
           (TypeB, digest_b),
       ]

Lazy Loading and Retries
~~~~~~~~~~~~~~~~~~~~~~~~

To avoid unnecessary overhead, ``fleche`` loads entry points lazily. If ``digest()`` encounters an object it doesn't know how to handle (an ``Unhashable`` error), it will:
1. Load all registered entry points.
2. Retry the digestion.

If a manual hook (via ``add_hook``) exists for a type provided by an entry point, the manual hook takes precedence and an ``INFO`` message is logged. If multiple entry points provide hooks for the same type, the first one encountered is used.
