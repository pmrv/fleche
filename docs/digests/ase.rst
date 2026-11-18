.. _fleche-ase:

ASE
===

How ``fleche`` digests and stores objects of the `Atomic Simulation Environment (ASE)
<https://wiki.fysik.dtu.dk/ase/>`_.

They are digested by the `fleche-ase <https://pypi.org/project/fleche-ase/>`_
companion package (``pip install fleche-ase``), an :doc:`entry point
<entry_points>` plugin that lives in the fleche repository, under
``src/fleche-ase``.  Without it ``fleche`` refuses them as
:exc:`~fleche.digest.Indigestible`.  It registers digest hooks for:

* ``ase.Atoms`` — digested from the cell, the periodic boundary conditions
  and all per-atom arrays (positions, atomic numbers, ...), plus the
  constraints and ``info`` when non-empty and the attached calculator when
  there is one.
  Two structures that differ only in their calculator get two keys, since
  ``get_potential_energy()`` answers differently for them.
* ``ase.constraints.FixConstraint`` and its subclasses (``FixAtoms``, ...) —
  digested from their ``todict()``, the same on their own as inside an
  ``Atoms``.
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

Storage
-------

When :doc:`destructuring <../storage/destructuring>`, an ``Atoms`` is a leaf
(depth 0, inlined like an ``int``) unless it carries a live calculator, which
is pickled with it and may be a whole model; then it stays opaque.
