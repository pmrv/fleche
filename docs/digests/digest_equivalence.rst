Digest Equivalence
==================

The :func:`fleche.digest.digest` function turns Python objects into SHA256 hex strings.
Those strings are the *only* thing the cache compares, so two objects that produce the
same digest are — for caching purposes — interchangeable.  Most of the time this is
exactly what you want: ``digest(1) == digest(1.0) == digest(1+0j)`` because all three
hold the same numeric value, and ``digest((1, 2)) != digest([1, 2])`` because the
container type matters.  This page documents the deliberate equivalences ``fleche``
guarantees, and the boundaries you should keep in mind.

The digest function is content-based: it walks each value, salts the running hash
with ``type(value).__name__`` for type discrimination, and folds in a representation
that is stable across processes and Python versions (where the underlying object's
representation allows it).  When two values *of different concrete Python types* are
considered equivalent at the value level (``1`` and ``1.0``, an ``int`` subclass with
the same numeric value, ...), the digest reflects that.

Dataclasses and ``attrs`` classes
---------------------------------

A stdlib :func:`dataclasses.dataclass` instance and an ``attrs``-decorated instance
hash identically when:

* they share the same class ``__name__``, and
* they expose the same ``(field_name, field_value)`` mapping.

This means you can convert a class from one record framework to the other without
invalidating any already-cached call that took an instance of that class as an
argument (or returned one).

.. code-block:: python

    from dataclasses import dataclass
    import attrs
    from fleche.digest import digest

    # before the migration
    @dataclass
    class Point:
        x: int
        y: int

    before = digest(Point(x=1, y=2))

    # after the migration — same name, same fields
    @attrs.define
    class Point:
        x: int
        y: int

    after = digest(Point(x=1, y=2))

    assert before == after

Why we make them equivalent
~~~~~~~~~~~~~~~~~~~~~~~~~~~

* **Persistence is the point.**  ``fleche`` is a *persistent* cache.  Migrating from
  ``@dataclass`` to ``@attrs.define`` (or back) is a routine refactor that should not
  silently throw away potentially expensive cached results.
* **Both are record types.**  The digest already only inspects attribute names and
  values; it never reads ``__init__``, ``__eq__``, ``__hash__``, or any of the other
  generated dunders.  Through that lens, an attrs record and a dataclass record with
  identical contents *are* identical.
* **Symmetric with numeric equivalence.**  ``digest(1) == digest(1.0) == digest(1+0j)``
  for the same reason: when two objects of different concrete types denote the same
  value, the digest collapses them.

Boundaries to keep in mind
~~~~~~~~~~~~~~~~~~~~~~~~~~

* **Equivalence is by class name, not module path.**  Two declarations with the same
  ``__name__`` but in different modules collide.  This was already true for
  dataclasses; it now extends to attrs.  If you have multiple classes named ``Point``
  in your project that mean different things, give them distinct names or override
  the digest per class (see :doc:`/dev/custom_digests`).
* **Class-level construction logic is bypassed on load.**  When ``fleche`` reads a
  destructured attrs / dataclass instance back from value storage, it reconstructs it
  via :py:func:`object.__new__` plus :py:func:`object.__setattr__`, intentionally
  bypassing ``__init__``, ``__post_init__``, attrs converters, and attrs validators.
  The same instance going *into* the cache may have been constructed through any of
  those; coming back out it will not.  In particular, validators do not re-run on
  load.  Make sure your validators express *invariants of the data*, not *side
  effects to perform on construction*.
* **Different runtime semantics still differ at runtime.**  ``slots``, ``frozen``,
  custom ``__eq__`` / ``__hash__``, attrs's ``eq_key``/``order_key``, ...  None of
  these affect the digest.  Two records that hash the same may still compare or
  iterate differently.  The digest tells you when ``fleche`` will reuse a cached
  result; it does not tell you the two instances are observationally identical.

Opting out per type
~~~~~~~~~~~~~~~~~~~

If a particular class needs stricter scoping than "same name + same fields", give it
a custom ``__digest__`` (see :doc:`/dev/custom_digests`).  For example, to scope by full
qualified path:

.. code-block:: python

    @dataclass
    class Point:
        x: int
        y: int

        def __digest__(self):
            from fleche.digest import digest
            return digest((f"{type(self).__module__}.{type(self).__qualname__}",
                           self.x, self.y))

A custom ``__digest__`` short-circuits the dataclass / attrs path and takes
precedence over both built-in cases.
