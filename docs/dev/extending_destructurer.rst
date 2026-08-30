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
(for hashing), :meth:`~fleche.storage.base.ChildItems.child_items` (see below),
and the class-method
:meth:`~fleche.storage.destructuring.Digested.sunder` (the ``sunder_fn``
itself, as a classmethod).  Study
:class:`~fleche.storage.destructuring.DigestedIterable` or
:class:`~fleche.storage.destructuring.DigestedDict` as the canonical
reference implementations before writing your own.

**Contract for** ``child_items``

``Digested`` inherits :class:`~fleche.storage.base.ChildItems`, the interface
every record holding other stored entries implements — the path layer's
``FileBlob`` and ``DirectoryBlob`` are the other implementors.  Return one
``(label, child)`` pair per slot the wrapper holds, where *child* is either an
inlined plain value or the :class:`~fleche.digest.Digest` of a separately
stored one; the *label* is free-form (``DigestedFields`` uses field names,
``DigestedIterable`` uses ``None``) and only has to mean something to your own
``mend``.

This is not optional bookkeeping.  It is the only thing that tells
:meth:`~fleche.caches.Cache.gc` your wrapper's children are still reachable: a
wrapper that omits a slot reports it as an orphan, and the next sweep evicts a
value your entry still points at — a ``KeyError`` on the following load, which
the wrapper reports as an ordinary cache miss.  Return **every** slot, keys of
a mapping included, whether or not it currently holds a ``Digest``.
