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
  library (see :ref:`fleche-ase` below; ``fleche``'s own numpy and pandas
  support ships the same way, as ``fleche-numpy`` and ``fleche-pandas``), or
* as a *library author* shipping ``fleche`` support for your own types
  alongside your library.

.. _fleche-ase:

``fleche-ase``: ASE Support
---------------------------

`fleche-ase <https://pypi.org/project/fleche-ase/>`_ is the canonical entry
point plugin; it lives in the fleche repository, under ``src/fleche-ase``.  It
registers digest hooks for the core types of the `Atomic Simulation
Environment (ASE) <https://wiki.fysik.dtu.dk/ase/>`_:

* ``ase.Atoms`` — digested from the cell, the periodic boundary conditions
  and all per-atom arrays (positions, atomic numbers, ...), plus the
  constraints and ``info`` when non-empty and the attached calculator when
  there is one.
  Two structures that differ only in their calculator get two keys, since
  ``get_potential_energy()`` answers differently for them.
* ``ase.calculators.calculator.Calculator`` and its subclasses — identified by
  the first of:

  1. an extractor registered for the class with
     ``fleche_ase.register_calculator`` (built in for ``EAM``,
     ``PyACECalculator``, ``GRACERuntimeCalculator``, ``TPCalculator`` and
     ``SinglePointCalculator``; file-backed potentials are keyed by the
     file's name and content),
  2. a non-empty ``todict()``,
  3. an empty ``todict()`` on a class listed in ``fleche_ase.PARAMETER_FREE``
     (``EMT``, ``LennardJones``, ``MorsePotential``, ``TIP3P``, ``TIP4P``).

  Any other calculator is :class:`~fleche.digest.Indigestible`: the call runs
  uncached, with a warning.
  So does a call on an ``Atoms`` carrying such a calculator.
* ``ase.vibrations.VibrationsData`` — digested from the underlying atoms,
  the vibrational indices and the 2D Hessian.
* ``ase.thermochemistry`` modes (``AbstractMode``) and objects
  (``BaseThermoChem``) — digested from the class name and the instance
  attributes.

Teach it a calculator it cannot identify by registering an extractor, a
function returning anything ``fleche`` can digest that tells two instances
apart:

.. code-block:: python

   from fleche_ase import register_calculator

   register_calculator("MyCalculator", lambda calc: (calc.model_path, calc.cutoff))
   register_calculator("MyFixedCalculator")  # no parameters: empty todict() is complete

Classes match by name along the MRO, so registering a base class covers its
subclasses.

With it installed, ``@fleche()``-decorated functions can accept and return
ASE objects with no further setup:

.. code-block:: bash

   pip install fleche-ase

.. code-block:: python

   from ase.build import bulk
   from fleche import fleche

   @fleche()
   def relax(structure):  # an ase.Atoms — digested via fleche-ase
       ...

   relax(bulk("Al"))

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
