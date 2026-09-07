Querying cached calls
=====================

Overview
--------
Fleche lets you retrieve previously cached calls that "match" a template using the query method. You can query either:

- From a function wrapper (recommended): ``myfunc.query(*args, metadata={...}, **kwargs)``
- From the active cache directly via a QueryCall template: ``cache().query(QueryCall(...))``
- From the active cache with keyword arguments instead of building a
  ``QueryCall`` by hand: ``cache().query(name="add")`` (accepts the same
  keywords as ``QueryCall``; passing both a template and keywords raises
  ``TypeError``)

When querying, any field in the template set to ``None`` acts as a wildcard. For arguments and result, values are compared using digest semantics (i.e., digest(template_value) == digest(stored_value)).


Querying from a wrapper
-----------------------
The wrapper-based API builds the correct Call template for you.

.. code-block:: pycon

   >>> from fleche import fleche, cache, tags

   >>> @fleche
   ... def add(a, b):
   ...     return a + b

   >>> # Run some calls under different metadata tags
   >>> with tags(project="alpha", phase="train"):
   ...     add(1, 2)
   ...     add(a=3, b=4)
   >>> with tags(project="beta", phase="eval"):
   ...     add(10, 5)

   >>> # Find calls with a=1, b=2 that are also tagged project="alpha"
   >>> # (omit positional args to match any a/b combination)
   >>> for call in add.query(1, 2, metadata={"tags": {"project": "alpha"}}):
   ...     assert call.name == "add"
   ...     assert call.metadata["tags"]["project"] == "alpha"
   ...     # call.result fetches the full result from value storage on access
   ...     print(call.result)                # e.g. 3
   ...     # call.arguments is a lazy proxy — each key triggers a separate load
   ...     print(call.arguments["a"])        # e.g. 1
   ...     print(dict(call.arguments))       # iterates keys, one load per key

Notes:
- ``metadata={"tags": {}}`` matches any call with a "tags" metadata entry (presence check).
- You can combine multiple metadata keys under a name (AND logic), e.g. ``{"tags": {"project": "alpha", "phase": "train"}}``.


Querying with a QueryCall template
-----------------------------------
You can also construct a ``QueryCall`` template manually and query against the active cache:

.. code-block:: pycon

   >>> from fleche.call import QueryCall
   >>> tpl = QueryCall(
   ...     name="add",             # or None for wildcard
   ...     arguments={"a": None},  # key present wildcard for argument 'a'
   ...     metadata={"tags": {"project": "alpha"}},
   ...     module=None,
   ...     version=None,
   ...     result=None,
   ... )
   >>> for call in cache().query(tpl):
   ...     print(call)


Behavior details
----------------
- None is a wildcard for any ``QueryCall`` field (``name``, ``module``, ``version``, ``result``, ``code_digest``) and also for individual argument values (interpreted as "key present").
- For arguments and result, equality is by digest: the template value and the stored value are each passed through :func:`~fleche.digest.digest` and the resulting hex strings are compared.  Pass a :class:`~fleche.digest.Digest` instance (e.g. via :func:`~fleche.D`) to match by a known digest without re-hashing; a plain ``str`` — even one that looks like a hex digest — is hashed as a string value and will not match.
- Metadata filtering supports presence checks (empty dict) and equality on simple types (str, bool, int, float). Complex types (e.g., lists) are handled correctly via client-side filtering.

.. warning::

   **Known trap (bug #916):** on a function decorated with
   ``hash_version=False`` or ``hash_module=False``, ``.query()`` silently
   matches nothing for calls made under it — even though ``.contains()``
   correctly returns ``True`` for the same call. The query template built by
   ``.query()`` always fills in the function's *real* ``version``/``module``,
   while the stored record has that field nulled out by the ``hash_version``/
   ``hash_module`` flag, so the two never match::

      >>> from fleche import fleche, cache
      >>> @fleche(version="v1", hash_version=False)
      ... def add(a, b): return a + b

      >>> with cache("memory"):
      ...     add(1, 2)
      ...     add.contains(1, 2)          # True
      ...     add.query(1, 2).count()     # 0 -- silently wrong

   The call *is* cached; only querying is broken. Until this is fixed,
   avoid ``.query()`` on functions decorated with ``hash_version=False`` or
   ``hash_module=False``, or query via ``cache().query(...)`` with an
   explicit ``QueryCall`` that sets those fields to ``None`` yourself.


Performance
-----------
When using the SQL backend, most simple filters (name/module/version/result/arguments and simple metadata predicates) are executed in the database for efficiency. Final results are then loaded and any remaining checks are applied client-side as needed.


QueryIterator API
-----------------

Both ``myfunc.query(...)`` and ``cache().query(...)`` return a
:class:`~fleche.query.QueryIterator`.  Iterating it yields
:class:`~fleche.call.LazyCall` objects; the iterator can be consumed
multiple times (each pass re-runs the underlying query) — with the
exception of ``.groupby()``'s returned iterators, see the note under
"Grouping" below.

Inspection
~~~~~~~~~~

``.count() -> int``
    Total number of matching calls.

``.empty() -> bool``
    ``True`` if there are no matching calls (cheaper than ``count() == 0``
    when the underlying query short-circuits).

``.any() -> LazyCall | None``
    First matching call, or ``None`` if empty.  Pair with ``.sorted()`` to
    control which call is returned.

``.only() -> LazyCall``
    The single matching call.  Raises :exc:`IndexError` if empty,
    :exc:`ValueError` if there is more than one match.

Filtering and ordering
~~~~~~~~~~~~~~~~~~~~~~

``.filter(predicate) -> QueryIterator``
    Keep only calls for which ``predicate(call)`` is truthy.  Lazy.

``.sorted(key=None, reverse=False) -> QueryIterator``
    Sort by *key*, where *key* is a callable ``(LazyCall) -> Any`` or
    a string argument name.  Lazy.

``.unique(key) -> QueryIterator``
    Remove duplicates, keeping the first call per group.  *key* is a
    callable or a string argument name.  Lazy.

``.take(n) -> QueryIterator``
    First *n* results.  Lazy.

``.skip(n) -> QueryIterator``
    Skip the first *n* results.  Lazy.

Temporal helpers
~~~~~~~~~~~~~~~~

Both need :class:`~fleche.metadata.Runtime` metadata (the default) to
produce a meaningful order. A call missing it is simply excluded from the
comparison — as long as at least one matching call has ``timestop``, the
result is a true extremum among those that do.

``.latest() -> LazyCall``
    Call with the most recent ``timestop``.  Raises :exc:`IndexError` if
    there are no matching calls at all, or :exc:`ValueError` if there are
    matching calls but none of them carry ``timestop``.

``.oldest() -> LazyCall``
    Call with the oldest ``timestop``.  Raises :exc:`IndexError` if there
    are no matching calls at all, or :exc:`ValueError` if there are
    matching calls but none of them carry ``timestop``.

Grouping
~~~~~~~~

``.groupby(key) -> dict[Any, QueryIterator]``
    Partition calls into a dict of ``QueryIterator`` objects.  *key* is a
    callable or a string argument name.  Materialises the full result set
    to build the groups.

.. note::

   ``.groupby()`` materializes its results eagerly; the returned
   ``QueryIterator``\ s are frozen snapshots of the calls matched at
   ``.groupby()``-call time and will **not** reflect later changes to the
   cache — unlike every other ``QueryIterator`` method, which re-runs the
   underlying query on each pass. Re-query (or re-``groupby``) if the cache
   may have changed since.

Results and side effects
~~~~~~~~~~~~~~~~~~~~~~~~

``.results() -> Iterator[Any]``
    Iterate over the *result values* of matching calls (triggers a value
    load per call).

``.table(arguments=(), results=False, shrink_keys=True) -> DataFrame``
    Return a :class:`~pandas.DataFrame` summarising the matched calls.
    Pass argument names (or ``True`` for all) via *arguments* to include
    them as columns; set ``results=True`` to add a ``result`` column.
    Metadata fields are flattened into columns automatically.  Index
    entries are shortened to their shortest unambiguous digest prefix
    unless ``shrink_keys=False``.

``.evict() -> None``
    Remove all matching calls from the cache.

``.transfer(target, pop=False, overwrite=False) -> None``
    Replay matching calls into *target* (another
    :class:`~fleche.caches.BaseCache`).  Skips entries already present
    unless ``overwrite=True``.  Set ``pop=True`` to evict them from the
    source after transfer.
