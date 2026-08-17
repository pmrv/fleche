Customizing Digests
===================

``fleche`` uses digests to identify objects and determine if a cached result can be reused. By default, it supports many built-in Python types, numpy arrays, dataclasses, and ``attrs``-decorated classes. For other types, or to customize how a digest is calculated, you can use one of the following methods.

The ``__digest__`` Method
-------------------------

The simplest way to customize the digest of an object is to implement a ``__digest__`` method on its class.
The method should return a :class:`~fleche.digest.Digest` (or a plain ``str``).

The recommended pattern is to call :func:`~fleche.digest.digest` on a tuple of the relevant fields.
This ensures that any field type ``fleche`` already knows how to hash (numpy arrays, dataclasses, nested objects, …) is handled correctly, and that different fields cannot accidentally collide:

.. code-block:: pycon

   >>> from fleche.digest import digest, Digest

   >>> class MyType:
   ...     def __init__(self, field1, field2):
   ...         self.field1 = field1
   ...         self.field2 = field2
   ...
   ...     def __digest__(self) -> Digest:
   ...         return digest((type(self).__name__, self.field1, self.field2))

Including ``type(self).__name__`` ensures that subclasses of ``MyType`` with otherwise identical field values still receive different digests.

.. note::

   Only include fields that affect the *result* of cached functions.
   Excluding irrelevant fields (e.g. display names, internal caches, attached metadata) makes more results reusable across calls.

Using ``add_hook``
------------------

If you cannot or do not want to modify a class, you can register a custom digest function using ``fleche.digest.add_hook``.

.. code-block:: pycon

   >>> from fleche.digest import add_hook, digest, Digest, Hook

   >>> class ExternalType:
   ...     def __init__(self, data):
   ...         self.data = data

   >>> def external_digest(obj: ExternalType) -> Digest:
   ...     return digest((type(obj).__name__, obj.data))

   >>> add_hook(Hook(ExternalType, external_digest))
   >>> # Or using a tuple
   >>> # add_hook((ExternalType, external_digest))

Hooks registered this way have the highest priority and will override any other digest logic for the given type.

Registering Entry Points
------------------------

Library authors who want to provide ``fleche`` support for their types without requiring users to manually call ``add_hook`` can register digest hooks through Python entry points, so that support loads automatically once their package is installed.

See :doc:`../digests/entry_points` for the full mechanism — the ``pyproject.toml`` declaration, lazy loading, precedence rules, and the ``fleche-ase`` plugin (digest hooks for ASE types) as a worked example.
