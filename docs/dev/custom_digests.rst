Customizing Digests
===================

``fleche`` uses digests to identify objects and determine if a cached result can be reused. By default, it supports many built-in Python types, numpy arrays, and dataclasses. For other types, or to customize how a digest is calculated, you can use one of the following methods.

The ``__digest__`` Method
-------------------------

The simplest way to customize the digest of an object is to implement a ``__digest__`` method on its class.
The method should return a :class:`~fleche.digest.Digest` (or a plain ``str``).

The recommended pattern is to call :func:`~fleche.digest.digest` on a tuple of the relevant fields.
This ensures that any field type ``fleche`` already knows how to hash (numpy arrays, dataclasses, nested objects, …) is handled correctly, and that different fields cannot accidentally collide:

.. code-block:: python

   from fleche.digest import digest, Digest

   class MyType:
       def __init__(self, field1, field2):
           self.field1 = field1
           self.field2 = field2

       def __digest__(self) -> Digest:
           return digest((type(self).__name__, self.field1, self.field2))

Including ``type(self).__name__`` ensures that subclasses of ``MyType`` with otherwise identical field values still receive different digests.

.. note::

   Only include fields that affect the *result* of cached functions.
   Excluding irrelevant fields (e.g. display names, internal caches, attached metadata) makes more results reusable across calls.

Using ``add_hook``
------------------

If you cannot or do not want to modify a class, you can register a custom digest function using ``fleche.digest.add_hook``.

.. code-block:: python

   from fleche.digest import add_hook, digest, Digest, Hook

   class ExternalType:
       def __init__(self, data):
           self.data = data

   def external_digest(obj: ExternalType) -> Digest:
       return digest((type(obj).__name__, obj.data))

   add_hook(Hook(ExternalType, external_digest))
   # Or using a tuple
   # add_hook((ExternalType, external_digest))

Hooks registered this way have the highest priority and will override any other digest logic for the given type.

Registering Entry Points
------------------------

For library authors who want to provide ``fleche`` support for their types without requiring users to manually call ``add_hook``, ``fleche`` supports Python entry points.

You can register your digest hooks in the ``fleche`` entry point group with the name ``digest`` in your ``pyproject.toml`` (or equivalent).

.. code-block:: toml

   [project.entry-points."fleche"]
   digest = "my_package.hooks:digest_hooks"

The entry point must resolve to one of:

* A single ``fleche.digest.Hook`` object.
* A tuple of ``(Type, Callable)``.
* A list containing any combination of the above.

These must be **module-level objects**, not callables that return hooks.
``fleche`` loads the entry point with ``importlib.metadata.EntryPoint.load()``,
which returns the object at the given path directly — it does **not** call it.

.. code-block:: python

   # my_package/hooks.py
   from fleche.digest import digest, Digest, Hook

   def type_a_digest(obj: TypeA) -> Digest:
       return digest((type(obj).__name__, obj.field1, obj.field2))

   def type_b_digest(obj: TypeB) -> Digest:
       return digest((type(obj).__name__, obj.relevant_field))

   digest_hooks = [
       Hook(TypeA, type_a_digest),
       (TypeB, type_b_digest),
   ]

Lazy Loading and Retries
~~~~~~~~~~~~~~~~~~~~~~~~

To avoid unnecessary overhead, ``fleche`` loads entry points lazily. If ``digest()`` encounters an object it doesn't know how to handle (an ``Indigestible`` error), it will:
1. Load all registered entry points.
2. Retry the digestion.

If a manual hook (via ``add_hook``) exists for a type provided by an entry point, the manual hook takes precedence and an ``INFO`` message is logged. If multiple entry points provide hooks for the same type, the first one encountered is used.
