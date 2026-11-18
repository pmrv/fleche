.. _entry-points:

Entry Points
============

``fleche`` is extensible through Python *entry points* (the standard
:mod:`importlib.metadata` plugin mechanism): any installed package can
register digest hooks for its types in the ``fleche`` entry point group under
the name ``digest``.  Installing such a package is all it takes — no imports,
no calls to :func:`~fleche.digest.add_hook`.  Entry points are loaded lazily
on demand (see "How Hooks Are Loaded" below for the full mechanism).

Use entry points whenever digest support for a type should "just work" after
a ``pip install``:

* as a *plugin package* that adds ``fleche`` support for a third-party
  library (see :ref:`fleche-ase`; ``fleche``'s own numpy and pandas
  support ships the same way, as ``fleche-numpy`` and ``fleche-pandas``), or
* as a *library author* shipping ``fleche`` support for your own types
  alongside your library.

How Hooks Are Loaded
--------------------

Entry points are loaded *lazily*: to avoid import overhead, nothing happens
until :func:`~fleche.digest.digest` raises
:class:`~fleche.digest.Indigestible` for a value.  At that point, and every
subsequent time the same thing happens, ``fleche``:

1. loads all entry points registered under the group ``fleche`` with the
   name ``digest``, and
2. retries the digestion.

Hooks match with ``isinstance``, so a hook registered for a base class (like
``fleche-ase``'s ``Calculator`` hook) also covers its subclasses.

Precedence rules:

* Hooks registered manually with :func:`~fleche.digest.add_hook` always take
  priority over entry point hooks; an ``INFO`` message is logged when one
  shadows the other.
* If multiple entry points provide hooks for the same type, the first one
  encountered wins.  Hooks for a subclass are tried before hooks for its
  bases, whichever distribution provides them, so a plugin's hook for an
  ``np.ndarray`` subclass takes precedence over ``fleche-numpy``'s.
* An entry point that fails to load is logged as an ``ERROR`` (with
  traceback) and skipped — it never breaks digestion of other values.
* Manual hooks take priority over a type's own ``__digest__`` method (see
  :doc:`/dev/custom_digests`), and ``__digest__`` takes priority over entry
  point hooks.  Entry points load lazily, so with them first a subclass
  defining ``__digest__`` would digest one way before they load and another
  way after.

Registering Your Own Entry Point
--------------------------------

Declare the entry point in the ``fleche`` group with the name ``digest`` in
your ``pyproject.toml`` (or equivalent):

.. code-block:: toml

   [project.entry-points."fleche"]
   digest = "my_package.hooks:digest_hooks"

The entry point must resolve to one of:

* a single :class:`~fleche.digest.Hook` object,
* a tuple of ``(Type, Callable)``, or
* a list containing any combination of the above.

These must be **module-level objects**, not callables that return hooks.
``fleche`` loads the entry point with ``importlib.metadata.EntryPoint.load()``,
which returns the object at the given path directly — it does **not** call it.

.. code-block:: pycon

   >>> from fleche.digest import digest, Digest, Hook

   >>> class TypeA:
   ...     def __init__(self, field1, field2):
   ...         self.field1 = field1
   ...         self.field2 = field2

   >>> class TypeB:
   ...     def __init__(self, relevant_field):
   ...         self.relevant_field = relevant_field

   >>> def type_a_digest(obj: TypeA) -> Digest:
   ...     return digest((type(obj).__name__, obj.field1, obj.field2))

   >>> def type_b_digest(obj: TypeB) -> Digest:
   ...     return digest((type(obj).__name__, obj.relevant_field))

   >>> digest_hooks = [
   ...     Hook(TypeA, type_a_digest),
   ...     (TypeB, type_b_digest),
   ... ]

For guidance on writing the digest functions themselves (which fields to
include, avoiding collisions), see :doc:`/dev/custom_digests`.
