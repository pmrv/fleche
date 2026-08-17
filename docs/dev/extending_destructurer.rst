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
  ``0`` when the value has no children to split, or ``float("inf")`` when the
  value cannot be handled.

The usual way to satisfy that contract is *not* to write ``sunder_fn`` by
hand.  :meth:`~fleche.storage.destructuring.Digested.sunder` is already a
concrete template method on the ABC: it enumerates child slots, interns each
one, computes the depth, and picks the inline-vs-store branch for you.  Pass
``YourDigested.sunder`` as the ``sunder_fn`` and implement the four abstract
methods it dispatches to:

- :meth:`~fleche.storage.destructuring.Digested._slots` — return the
  ``(label, child)`` pairs to recurse into, or ``None`` to opt out (which is
  what yields the ``float("inf")`` depth).
- :meth:`~fleche.storage.destructuring.Digested._rebuild_plain` — rebuild the
  value when no child became a :class:`~fleche.digest.Digest` reference.
- :meth:`~fleche.storage.destructuring.Digested._rebuild_digest` — build the
  wrapper instance when at least one child did.
- :meth:`~fleche.storage.destructuring.Digested.mend` — reconstruct the
  original value from storage.

:meth:`~fleche.storage.destructuring.Digested.underlying` (for hashing) is
abstract as well and must be implemented either way.  Overriding ``sunder``
directly is possible but rarely worth it: the three ``_``-prefixed methods
stay abstract, so you would still need to define them to make the class
instantiable.  Study
:class:`~fleche.storage.destructuring.DigestedIterable` or
:class:`~fleche.storage.destructuring.DigestedDict` as the canonical
reference implementations — neither overrides ``sunder``.
