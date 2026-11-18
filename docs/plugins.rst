.. _plugins:

Plugins
=======

Support for third-party libraries ships as companion packages that register
themselves via :doc:`entry points <digests/entry_points>`.  Installing one
alongside ``fleche`` is all it takes; without it, ``fleche`` refuses the
library's types as :exc:`~fleche.digest.Indigestible` and the storage treats
them as opaque.

Each package declares how its types are digested and how they are
:doc:`destructured <storage/destructuring>` on storage:

* ``fleche-numpy`` — arrays, ``np.bool_`` and ``np.timedelta64``; see
  :doc:`digests/numpy`.
* ``fleche-pandas`` — ``DataFrame``, ``Series``, ``Index``, ``pd.Timedelta``
  and ``pd.NA``; see :doc:`digests/pandas`.  Pulls in ``fleche-numpy``.
* ``fleche-ase`` — ``Atoms``, constraints, calculators and more from the
  Atomic Simulation Environment; see :doc:`digests/ase`.

.. toctree::
   :maxdepth: 1

   digests/numpy
   digests/pandas
   digests/ase
