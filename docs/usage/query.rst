Querying cached calls
=====================

Overview
--------
Fleche lets you retrieve previously cached calls that "match" a template using the query method. You can query either:

- From a function wrapper (recommended): ``myfunc.query(*args, metadata={...}, **kwargs)``
- From the active cache directly via a QueryCall template: ``cache().query(QueryCall(...))``

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


Performance
-----------
When using the SQL backend, most simple filters (name/module/version/result/arguments and simple metadata predicates) are executed in the database for efficiency. Final results are then loaded and any remaining checks are applied client-side as needed.
