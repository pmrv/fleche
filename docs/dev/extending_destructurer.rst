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

Registering from a package
--------------------------

A package lists its ``(predicate, sunder_fn)`` pairs under the ``fleche`` entry
point ``destructure`` instead of calling ``register_destructurer`` itself:

.. code-block:: toml

   [project.entry-points.'fleche']
   destructure = 'mypackage.destructure:destructurers'

fleche registers them once, before the first save of any destructuring store,
so they apply from the first value on.  fleche-numpy registers its
``dtype=object`` array destructurer this way.

An entry may carry a third element, ``size(value) -> int``, for the store's
``remaining_size``: an estimate of how many bytes *value* holds itself (the
children its destructurer interns add their own).  It is bytes-ish, not exact:
read it from what is cheap, such as an array's ``nbytes``, never by
serializing the value, and accept that it may be off by a good margin.
Without it, the value counts as holding nothing itself.

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

:meth:`~fleche.storage.destructuring.Digested.mend`,
:meth:`~fleche.storage.destructuring.Digested.underlying` (for hashing) and
:meth:`~fleche.storage.base.ChildItems.child_items` (see `Contract for
child_items`_ below) are also abstract and must be implemented, but none of
them is part of ``sunder``'s own dispatch. ``mend`` is the *inverse* hook: it is invoked separately, by
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

   @dataclass
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

Contract for ``child_items``
----------------------------

``Digested`` inherits :class:`~fleche.storage.base.ChildItems`, the interface
every record holding other stored entries implements.  Return one
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
``DigestedFields`` subclasses get it for free from their ``_field_items``.
