.. _function-profile:

Per-function metadata: ``FunctionProfile``
==========================================

All static per-function metadata is consolidated in the frozen dataclass
:class:`~fleche.call.FunctionProfile` (defined in :mod:`fleche.call`).  The
class method ``FunctionProfile.of(func)`` performs every introspection step
in one place:

- ``inspect.signature`` for argument binding and ``Required`` positional-only
  checks
- ``pyiron_snippets.versions.VersionInfo`` for ``qualname``, ``module``, and
  ``version``
- ``func.__code__`` hashing plus the variables the function captured from
  enclosing scopes *and its argument defaults* (``__defaults__`` /
  ``__kwdefaults__``) (``code_digest``, via the module-level
  ``_code_digest``).  Closures out of one factory share a code object, so
  hashing the code alone handed them the same cache key — this distinguishes
  not just ``make(1)`` from ``make(2)`` (closures) but also
  ``lambda x, n=1`` from ``lambda x, n=2`` (defaults).  A capture or default
  that cannot be digested falls back to the code-only digest — decorating a
  closure over a database handle has to keep working — and warns, since the
  collision comes back with it
- ``get_type_hints(include_extras=True)`` to detect ``Ignored`` /
  ``Required`` annotations (populates ``ignored`` / ``required`` fields)

The result is stored by ``_profile``, a module-level
``lru_cache(maxsize=1000)`` keyed on the callable's identity.  Unhashable
callables (those that cannot serve as an ``lru_cache`` key) fall back to
``_profile.__wrapped__`` (bypassing the LRU cache) so they are handled
correctly without special-casing at call sites.

**Adding new per-function metadata** is a two-step operation: add a field to
``FunctionProfile`` and populate it inside ``FunctionProfile.of``.  Downstream
code then reads it from the profile instead of calling introspection APIs
directly.

See :doc:`/usage/helpers` ("Per-Function Static Caching") for the
user-facing behavior and caveats — including the "mutating ``func`` after
the first call isn't picked up" gotcha and how to clear the cache via
``_profile.cache_clear()``.
