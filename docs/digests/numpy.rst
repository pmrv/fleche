numpy
=====

How ``fleche`` digests numpy values.  numpy number scalars, such as
``np.int64`` or ``np.float32``, are numbers and digest by their exact value;
see :doc:`digest_equivalence`.

Timedeltas
----------

An ``np.timedelta64`` digests by its exact length, down to numpy's finest
unit, the attosecond, whatever unit it is stored in:
``np.timedelta64(5, "s")``, ``np.timedelta64(5000, "ms")`` and
``np.timedelta64(500, "10ms")`` digest alike.  numpy's own ``==`` is not the
reference: it compares two units in int64 after casting both to the finer one,
which can wrap around.

Three kinds have no fixed length and digest apart from every fixed one:

* years and months (``Y``, ``M``) by their number of months, so
  ``np.timedelta64(1, "Y")`` digests like ``np.timedelta64(12, "M")``;
* a unitless ``np.timedelta64(5)`` by its count;
* ``NaT`` alike in every unit.

numpy registers ``np.timedelta64`` as a ``numbers.Integral`` and calls
``np.timedelta64(5, "s") == 5``, but a timedelta64 never digests like a number.

This covers single values.  An array of ``timedelta64`` dtype digests by its
dtype and raw bytes, like every array, so there the unit matters:
``np.array([5], "m8[s]")`` and ``np.array([5000], "m8[ms]")`` digest apart.
