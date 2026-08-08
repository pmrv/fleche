.. _extending-destructurer:

Extending the destructurer
==========================

The ``DestructuringMixin`` type-dispatch table, ``_DESTRUCTURERS``, is a
module-level list of ``(predicate, sunder_fn)`` pairs.  It ships with four
built-in entries — lists/tuples, dicts, dataclasses, and attrs instances — and
can be extended at import time via
:func:`~fleche.storage.destructuring.register_destructurer`.  (See
:doc:`../storage/destructuring` for what destructuring does in the first
place.)

.. warning::

   ``_DESTRUCTURERS`` is a global, mutable list shared by every
   :class:`~fleche.storage.destructuring.DestructuringMixin` instance.
   ``_intern_rec`` reads it on every call, so a newly registered destructurer
   applies immediately to all subsequent saves — but entries already stored
   were split with the old logic.  Loading those entries after registration
   may produce inconsistent results.  Register all destructurers before any
   storage instance is first used.

Before reaching for this function, consider whether implementing
``__digest__`` (or ``add_hook``, see :doc:`custom_digests`) on the type in
question is sufficient.  Destructurer registration is only necessary when a
container type must have its *children* stored as independent, reusable keys
rather than being pickled as a single opaque blob.

**Contract for** ``sunder_fn``

The function must have the signature ``(intern, value) -> (result, depth)``
where:

- ``intern`` is :meth:`~fleche.storage.destructuring.DestructuringMixin._intern_rec`
  — call it on each child value and collect the returned ``(child, depth)``
  pairs.
- ``result`` must be either the plain value (when all children are inlined,
  i.e. no child returned a :class:`~fleche.digest.Digest`) or a new
  :class:`~fleche.storage.destructuring.Digested` subclass instance wrapping
  the children.
- ``depth`` must be ``1 + max(child_depths)`` when children were processed,
  or ``float("inf")`` when the value cannot be handled.

The ``Digested`` subclass must implement :meth:`~fleche.storage.destructuring.Digested.mend`
(reconstruction from storage), :meth:`~fleche.storage.destructuring.Digested.underlying`
(for hashing), and the class-method
:meth:`~fleche.storage.destructuring.Digested.sunder` (the ``sunder_fn``
itself, as a classmethod).  Study
:class:`~fleche.storage.destructuring.DigestedIterable` or
:class:`~fleche.storage.destructuring.DigestedDict` as the canonical
reference implementations before writing your own.

.. note::

   The reference-graph helpers only recognise the built-in wrappers.
   :meth:`~fleche.storage.destructuring.DestructuringMixin._raw_sub_digests`
   pattern-matches
   :class:`~fleche.storage.destructuring.DigestedIterable`,
   :class:`~fleche.storage.destructuring.DigestedDict`, and
   :class:`~fleche.storage.destructuring.DigestedFields`, and the no-load
   scanners (see :ref:`destructuring-no-load`) match the same four classes by
   name.  A wrapper subclassing :class:`~fleche.storage.destructuring.Digested`
   directly is invisible to both, and one subclassing a built-in wrapper is
   seen by the loading path but not by the scanners.  Entries stored through
   such a wrapper therefore read as childless to
   :meth:`~fleche.storage.destructuring.DestructuringMixin.count_reuses` and to
   :meth:`~fleche.caches.Cache.gc` — which for ``gc`` means their children look
   collectable.  If your destructurer only needs to reach a new container
   *type*, have its ``sunder_fn`` return one of the built-in wrappers rather
   than a new class, and both paths keep following the references.
