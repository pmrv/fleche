Querying cached calls
=====================

Overview
--------
Fleche lets you retrieve previously cached calls that "match" a template using the query method. You can query either:

- From a function wrapper (recommended): ``myfunc.query(*args, metadata={...}, **kwargs)``
- From the active cache directly via a Call template: ``cache().query(Call(...))``

When querying, any field in the template set to ``None`` acts as a wildcard. For arguments and result, values are compared using digest semantics (i.e., digest(template_value) == digest(stored_value)).


Querying from a wrapper
-----------------------
The wrapper-based API builds the correct Call template for you and decodes values on return.

Example::

    from fleche import fleche, cache, tags

    @fleche
    def add(a, b):
        return a + b

    # Run some calls under different metadata tags
    with tags(project="alpha", phase="train"):
        add(1, 2)
        add(a=3, b=4)
    with tags(project="beta", phase="eval"):
        add(10, 5)

    # Find calls tagged with project="alpha"
    for call in add.query(1, 2, metadata={"tags": {"project": "alpha"}}):
        assert call.name == "add"
        assert call.metadata["tags"]["project"] == "alpha"
        # arguments and result are decoded from the value storage
        print(call.arguments, call.result)

Notes:
- ``metadata={"tags": {}}`` matches any call with a "tags" metadata entry (presence check).
- You can combine multiple metadata keys under a name (AND logic), e.g. ``{"tags": {"project": "alpha", "phase": "train"}}``.


Querying with a Call template
-----------------------------
You can also construct a Call template manually and query against the active cache::

    from fleche.call import Call
    tpl = Call(
        name="add",             # or None for wildcard
        arguments={"a": None},  # key present wildcard for argument 'a'
        metadata={"tags": {"project": "alpha"}},
        module=None,
        version=None,
        result=None,
    )
    for call in cache().query(tpl):
        print(call)


Behavior details
----------------
- None is a wildcard for name/module/version and also for individual argument values (interpreted as "key present").
- For arguments and result, equality is by digest (so Digest objects and matching 64-char hex strings are treated equivalently).
- Metadata filtering supports presence checks (empty dict) and equality on simple types (str, bool, int, float). Complex types (e.g., lists) are handled correctly via client-side filtering.


Performance
-----------
When using the SQL backend, most simple filters (name/module/version/result/arguments and simple metadata predicates) are executed in the database for efficiency. Final results are then loaded and any remaining checks are applied client-side as needed.
