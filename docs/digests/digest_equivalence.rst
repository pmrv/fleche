Digest Equivalence
==================

The :func:`fleche.digest.digest` function turns Python objects into SHA256 hex strings.
Those strings are the *only* thing the cache compares, so two objects that produce the
same digest are — for caching purposes — interchangeable.  Most of the time this is
exactly what you want: ``digest(1) == digest(1.0) == digest(1+0j)`` because all three
hold the same numeric value, and ``digest((1, 2)) != digest([1, 2])`` because the
container type matters.  This page documents the deliberate equivalences ``fleche``
guarantees, and the boundaries you should keep in mind.

The digest function is content-based: it walks each value, typically salts the
running hash with ``type(value).__name__`` for type discrimination, and folds in a
representation that is stable across processes and Python versions (where the
underlying object's representation allows it).

Number types (``int``, ``float``, ``complex``, and subclasses) are an explicit
exception: their digest is computed via Python's numeric hash protocol
(``hash(value)``), which itself guarantees ``hash(1) == hash(1.0) == hash(1+0j)``.
The type name is therefore **not** carried into the final digest for numbers, which is
precisely why ``digest(1) == digest(1.0) == digest(1+0j)``.

``bool`` is the one numeric subclass excluded from this equivalence: it keeps
its own type-name salt, so ``digest(True) != digest(1)`` even though
``isinstance(True, int)``.

For all other types the type-name salt is applied normally, so
``digest((1, 2)) != digest([1, 2])`` because "tuple" and "list" diverge before
the elements are processed.

Dataclasses and ``attrs`` classes
---------------------------------

A stdlib :func:`dataclasses.dataclass` instance and an ``attrs``-decorated instance
hash identically when:

* they share the same class ``__name__``, and
* they expose the same ``(field_name, field_value)`` mapping.

This means you can convert a class from one record framework to the other without
invalidating any already-cached call that took an instance of that class as an
argument (or returned one).

.. code-block:: pycon

    >>> from dataclasses import dataclass
    >>> import attrs
    >>> from fleche.digest import digest

    >>> # before the migration
    >>> @dataclass
    ... class Point:
    ...     x: int
    ...     y: int

    >>> before = digest(Point(x=1, y=2))

    >>> # after the migration — same name, same fields
    >>> @attrs.define
    ... class Point:
    ...     x: int
    ...     y: int

    >>> after = digest(Point(x=1, y=2))

    >>> assert before == after

Why We Make Them Equivalent
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

Boundaries to Keep in Mind
~~~~~~~~~~~~~~~~~~~~~~~~~~

* **Equivalence is by class name, not module path.**  Two declarations with the same
  ``__name__`` but in different modules collide.  This was already true for
  dataclasses; it now extends to attrs.  If you have multiple classes named ``Point``
  in your project that mean different things, give them distinct names or override
  the digest per class (see :doc:`/dev/custom_digests`).
* **Class-level construction logic is bypassed on load.**  When ``fleche`` reads a
  destructured attrs / dataclass instance back from value storage, it reconstructs it
  via :py:meth:`object.__new__` plus :py:meth:`object.__setattr__`, intentionally
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

Opting Out per Type
~~~~~~~~~~~~~~~~~~~

If a particular class needs stricter scoping than "same name + same fields", give it
a custom ``__digest__`` (see :doc:`/dev/custom_digests`).  For example, to scope by full
qualified path:

.. code-block:: pycon

    >>> @dataclass
    ... class Point:
    ...     x: int
    ...     y: int
    ...
    ...     def __digest__(self):
    ...         from fleche.digest import digest
    ...         return digest((f"{type(self).__module__}.{type(self).__qualname__}",
    ...                        self.x, self.y))

A custom ``__digest__`` short-circuits the dataclass / attrs path and takes
precedence over both built-in cases.

Functions and Closures
----------------------

A function digests by its **code object plus the state bound alongside it** —
the variables it captured from enclosing scopes and its argument defaults.  Two
functions compiled from the same source that capture nothing and default nothing
digest identically — the digest is about the code, not about where the
function lives or what it is called:

.. code-block:: pycon

    >>> from fleche.digest import digest

    >>> def add_one(x):
    ...     return x + 1

    >>> def also_add_one(x):
    ...     return x + 1

    >>> assert digest(add_one) == digest(also_add_one)

Closures handed out by the same factory share that one code object, so the
captured cells are the only thing that tells them apart:

.. code-block:: pycon

    >>> def adder(n):
    ...     def add(x):
    ...         return x + n
    ...     return add

    >>> assert digest(adder(1)) != digest(adder(2))
    >>> assert digest(adder(1)) == digest(adder(1))

Argument defaults count for the same reason.  They are evaluated once at
definition time and live on the function object, not in the code, so two
definitions that differ only in a default share a code object:

.. code-block:: pycon

    >>> assert digest(lambda x, n=1: x + n) != digest(lambda x, n=2: x + n)

That covers the ``k=n`` idiom for avoiding late binding, which captures the
enclosing value in a default rather than in a cell:

.. code-block:: pycon

    >>> def scaler(n):
    ...     def scale(x, k=n):
    ...         return x * k
    ...     return scale

    >>> assert digest(scaler(2)) != digest(scaler(3))

Keyword-only defaults (``__kwdefaults__``) are folded in the same way.  For a
decorated function, defaults also reach the cache key by a second route
regardless of ``hash_code``: :meth:`~fleche.call.Call.from_call` applies them
when binding, so an unsupplied argument is recorded at its default value.

Reaching the cache key requires ``hash_code=True``: the decorator leaves
``code_digest`` out of the key by default, and two closures out of one factory
agree on qualified name and module, so without that flag they still share an
entry.

Boundaries for Function Digests
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* **Only captured variables count, not globals.**  A function that reads a
  module-level constant digests the same before and after that constant is
  rebound — globals are looked up at call time and are not part of the function
  object.  Use ``version=`` to invalidate when a global your function depends on
  changes.
* **Captures and defaults are read at digest time.**  Mutating (or rebinding) a
  captured variable changes the digest of the closure, and so does mutating a
  mutable default — the accumulating ``def f(x, acc=[])`` idiom keeps state
  between calls, and the digest follows it.  That is the point, but it means a
  function over mutable state has no single digest.
* **A capture or default that cannot be digested is refused, not skipped.**
  Digesting a function that holds an object ``fleche`` does not know how to hash
  raises :exc:`~fleche.digest.Indigestible`, just like passing that object as an
  argument would.  The decorator itself degrades instead of failing: it warns
  and falls back to a code-only ``code_digest``, which brings the collision
  between closures from one factory back with it.
* **A method's implicit class capture is identified by name.**  Mentioning
  ``super()`` (or ``__class__``) makes the compiler hand the method a
  ``__class__`` cell holding the class it was defined in.  User-defined classes
  are :exc:`~fleche.digest.Indigestible` as values, so that cell is folded in as
  ``module.QualName`` instead — otherwise every method calling ``super()`` would
  be refused.
* **Cycles are cut with a back-reference.**  A recursive inner function
  captures itself, two closures can capture each other, and a function can be
  reached from its own defaults — digesting those by value would recurse
  forever.  When the walk meets a function it is already digesting, it folds in
  a marker naming *how far back up the walk* that function sits, instead of
  descending again.  The distance matters: a plain "seen it" marker gives
  ``a -> b -> a`` and ``c -> d -> d`` the same digest, though one ping-pongs
  between two functions and the other recurses on the second.  Being relative,
  the marker also makes a cycle digest the same wherever the walk meets it.
  Everything else about those functions — code, captures, defaults — is folded
  in where the walk first reached them.
* **A bound method carries its receiver.**  ``obj.method`` digests as the
  underlying function *plus* ``obj``, so two instances do not share a digest —
  and a method bound to an object ``fleche`` cannot hash is refused, exactly as
  that object would be as an argument.  A classmethod's receiver is a class, so
  it is named rather than valued.  The decorator is unaffected: a bound method's
  ``code_digest`` is taken from the underlying function, because the receiver
  already arrives as an ordinary argument of the call.
* **Decorated functions digest as what they wrap.**  ``digest(fleche()(f)) ==
  digest(f)`` — the decoration is transparent, so a cached function does not
  care whether it is handed the raw or the cached callable.

Giving a Function Its Own Digest
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Every function shares one type, so a class-level ``__digest__`` could never
distinguish them; for functions the attribute is therefore read off the function
object itself.  That is the escape hatch when a closure captures something
unhashable but you know what actually matters:

.. code-block:: pycon

    >>> def make_query(connection, table):
    ...     def run():
    ...         return connection.execute(f"SELECT * FROM {table}")
    ...     # the connection is not part of the result's identity, the table is
    ...     run.__digest__ = lambda: digest(("run", table))
    ...     return run
