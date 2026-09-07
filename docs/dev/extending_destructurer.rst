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
``YourDigested.sunder`` as the ``sunder_fn`` and implement the three abstract
classmethod hooks it dispatches to:

- :meth:`~fleche.storage.destructuring.Digested._slots` — return the
  ``(label, child)`` pairs to recurse into, or ``None`` to opt out (which is
  what yields the ``float("inf")`` depth).
- :meth:`~fleche.storage.destructuring.Digested._rebuild_plain` — rebuild the
  value when no child became a :class:`~fleche.digest.Digest` reference.
- :meth:`~fleche.storage.destructuring.Digested._rebuild_digest` — build the
  wrapper instance when at least one child did.

:meth:`~fleche.storage.destructuring.Digested.mend` and
:meth:`~fleche.storage.destructuring.Digested.underlying` (for hashing) are
also abstract and must be implemented, but neither is part of ``sunder``'s
own dispatch. ``mend`` is the *inverse* hook: it is invoked separately, by
:meth:`~fleche.storage.destructuring.DestructuringMixin.load` on the
**read** path, a completely different call site from ``sunder`` (the
**write**/intern path) — ``sunder`` never calls ``mend``.

Overriding ``sunder`` directly is possible but rarely worth it: the three
``_``-prefixed methods stay abstract, so you would still need to define them
to make the class instantiable.  Study
:class:`~fleche.storage.destructuring.DigestedIterable` or
:class:`~fleche.storage.destructuring.DigestedDict` as the canonical
reference implementations for the *collection* shape — neither overrides
``sunder``.  For the *record* shape (a fixed set of named fields rather than
an arbitrary-length collection), see `Record-shaped types: DigestedFields`_
below, which needs even less code.

Record-shaped types: ``DigestedFields``
----------------------------------------

Not every custom type is collection-shaped.  When the type you want to
destructure is *record*-shaped — a fixed set of named fields, as with a
dataclass, an ``attrs`` class, or any plain object with a handful of
attributes — implementing :class:`~fleche.storage.destructuring.Digested`
from scratch is more work than it needs to be.
:class:`~fleche.storage.destructuring.DigestedFields` is a concrete
intermediate base (itself a ``Digested`` subclass) that already implements
``_slots``, ``_rebuild_plain``, ``_rebuild_digest``, ``mend``, and
``underlying`` generically for any record-shaped value — it reconstructs
instances via ``object.__new__`` plus ``__setattr__``, bypassing ``__init__``
/``__post_init__``, so ``InitVar``, ``init=False``, frozen, and slotted
fields all round-trip correctly. That leaves exactly **one** abstract hook
for a subclass to fill in:

- :meth:`~fleche.storage.destructuring.DigestedFields._field_items` — a
  ``@staticmethod`` returning ``[(name, value), ...]`` for a live instance.

This is the pattern the two built-in record destructurers actually use:
:class:`~fleche.storage.destructuring.DigestedDataclass` and
:class:`~fleche.storage.destructuring.DigestedAttrs` are each a one-method
``_field_items`` override of ``DigestedFields``. For example,
``DigestedDataclass`` in full:

.. code-block:: python

   class DigestedDataclass(DigestedFields):
       @staticmethod
       def _field_items(value):
           return [(f.name, getattr(value, f.name)) for f in dataclasses.fields(value)]

Study whichever of the two canonical shapes matches your type — collection
(:class:`~fleche.storage.destructuring.DigestedIterable` /
:class:`~fleche.storage.destructuring.DigestedDict`) or record
(:class:`~fleche.storage.destructuring.DigestedFields`, via
``DigestedDataclass``/``DigestedAttrs``) — before writing a ``Digested``
subclass from scratch: picking the shape that matches is usually far less
code than implementing all three ``_``-prefixed hooks yourself.
