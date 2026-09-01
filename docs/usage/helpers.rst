Decorator Helpers
=================

Functions decorated with ``@fleche`` are enhanced with several helper methods that allow for manual interaction with the cache and inspection of function calls.

Helper Methods
--------------

The following methods are added to the decorated function:

``.call(*args, **kwargs)``
~~~~~~~~~~~~~~~~~~~~~~~~~~

Returns a ``Call`` object representing the cache key for the given arguments.
The object carries the function name, module, version, and the arguments that
participate in the key — but it is **not** a complete record of the call:

- Arguments annotated with :class:`~fleche.call.Ignored` are stripped from
  ``call.arguments``.
- ``version``, ``module``, and ``code_digest`` are set to ``None`` when the
  corresponding ``hash_*`` flag is ``False``.

The function is not executed.

``.digest(*args, **kwargs)``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Returns the unique cache key (a digest string) that would be used for the given call.

``.load(*args, **kwargs)``
~~~~~~~~~~~~~~~~~~~~~~~~~~

Attempts to load the result of a specific call from the cache. If the result is not cached, it raises a ``KeyError``.

``.contains(*args, **kwargs)``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Returns ``True`` if the result for the given call is already present in the cache, ``False`` otherwise.

``.query(*args, metadata={}, **kwargs)``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Returns a :class:`~fleche.query.QueryIterator` over matching cached calls from the active cache. Any argument passed as ``None`` acts as a wildcard, matching any stored value for that parameter. The ``metadata`` keyword argument accepts a dictionary of metadata tags to further filter results (e.g., ``metadata={"tags": {"project": "alpha"}}``). The iterator supports chainable methods such as ``.filter()``, ``.table()``, ``.count()``, ``.results()``, ``.evict()``, and more.

.. warning::

   If the decorated function has a parameter named ``metadata``, that parameter
   is shadowed by ``.query()``'s own ``metadata=`` keyword and **cannot** be
   passed as a keyword argument.  Pass it positionally instead::

      # function signature: def fetch(user_id, metadata):
      fetch.query(123, "v1")           # positional — works
      fetch.query(user_id=123, metadata="v1")  # shadowed — 'metadata' is passed
                                               # as the filter value and raises
                                               # AttributeError (a str has no
                                               # .items()), since .query()'s
                                               # metadata= expects a dict

   ``fleche`` logs a ``WARNING`` whenever the decorated function has a
   parameter named ``metadata`` — on every call, positional or not. It is
   informational, not an indicator that a particular call failed.

See :doc:`query` for a detailed guide on querying cached calls.

``.rerun(*args, **kwargs)``
~~~~~~~~~~~~~~~~~~~~~~~~~~~

Forces the function to re-execute, even if its result is already present in the cache, and saves the newly computed result to the cache (unless the result is ``None``, in which case any prior cached result is evicted instead — see :ref:`none-not-cached` below). This forces reevaluation recursively for any nested ``@fleche`` calls as well.

``.bind(*args, **kwargs)``
~~~~~~~~~~~~~~~~~~~~~~~~~~

Returns a :class:`~fleche.state.BoundWrapper` that captures the active cache and metadata at the moment ``.bind()`` is invoked. The bound wrapper is a plain callable — it does not carry the ``fleche`` helper namespace.

Optionally pre-applies ``*args`` and ``**kwargs`` via :func:`functools.partial`. This is useful when work needs to be submitted to a process pool where the cache context must travel with the callable.

.. code-block:: pycon

   >>> from fleche import fleche, cache

   >>> @fleche
   ... def add(a, b):
   ...     return a + b

   >>> with cache("memory"):
   ...     bound = add.bind()   # freezes the active "memory" cache
   ...
   >>> # bound carries the "memory" cache — callable anywhere, no context needed
   >>> result = bound(1, 2)
   >>> assert result == 3

   >>> # Pre-apply arguments — bind inside the context, call outside it
   >>> with cache("memory"):
   ...     bound_partial = add.bind(1, 2)
   ...
   >>> # bound_partial carries the "memory" cache even though the context has exited
   >>> result = bound_partial()   # equivalent to add(1, 2) in the frozen context
   >>> assert result == 3

See :class:`~fleche.state.BoundWrapper` for the full API, including pickling support.

.. _none-not-cached:

Functions Returning ``None``
-----------------------------

Functions that return ``None`` are **never cached**.  When a decorated function
returns ``None``, ``fleche`` logs a ``WARNING`` and skips the save step
entirely.  Subsequent calls will execute the function again rather than
returning a cached value.

This applies to all code paths, with one difference for ``.rerun()``:

- A normal call that returns ``None`` does not cache.
- ``.rerun()`` re-executes the function and still does not cache if the new
  result is ``None`` — but since a prior cached entry may now be stale, it is
  **evicted** so that later calls fall through to re-execution rather than
  returning the old value. If the active cache rejects the eviction (e.g. a
  read-only cache), ``fleche`` only logs a ``WARNING`` — the stale entry is
  left in place, and you must evict it yourself::

     >>> from fleche import cache
     >>> key = my_func.digest(*args, **kwargs)
     >>> cache().evict(key)

Accessing the Original Function
-------------------------------

The original, undecorated function is always accessible via the ``.__wrapped__`` attribute. This is useful if you need to bypass the cache entirely for a specific call.

.. code-block:: pycon

   >>> @fleche
   ... def my_func(x):
   ...     return x * 2

   >>> # Bypass cache
   >>> result = my_func.__wrapped__(10)

Per-Function Static Caching
---------------------------

To keep the cache-hit hot path fast, ``@fleche`` computes a
:class:`~fleche.call.FunctionProfile` the first time it sees a given function
and caches it for the lifetime of the process.  A profile captures all static
per-function metadata in one frozen dataclass:

- ``inspect.signature(func)`` — used for argument binding
- the digest of ``func.__code__`` together with the state bound alongside it —
  the variables captured from enclosing scopes and the argument defaults
  (included in cache keys only when ``hash_code=True``; the default is
  ``False``, so closures out of one factory share a key unless it is enabled)
- ``(qualname, module, version)`` extracted via
  ``VersionInfo`` — ``module`` and ``version``
  are included in cache keys by default (``hash_module=True``,
  ``hash_version=True``); set either flag to ``False`` to exclude the
  corresponding field from the key
- the sets of :class:`~fleche.call.Ignored`- and
  :class:`~fleche.call.Required`-annotated argument names

All fields are stored in a single frozen :class:`~fleche.call.FunctionProfile`
dataclass, backed by one ``_profile`` LRU cache (max 1000 entries) keyed on
the callable's identity.  Subsequent calls re-use the cached profile instead
of re-introspecting on every invocation.  The cache is process-scoped and has
no effect on the persistent fleche backends.

.. warning::

   **Mutating ``func`` after the first call is not picked up.**  Changes to
   ``func.__code__``, ``func.__signature__``, ``func.__module__``,
   ``func.__qualname__``, or ``func.__version__`` made after the wrapper has
   already seen ``func`` once will not affect subsequent cache keys.

   In practice this matters only for code that hot-mutates dunder attributes
   on a live function — typically ``Mock`` instances in tests, or
   monkey-patching experiments.  Decorators that return a *new* wrapped
   callable, and ``importlib.reload`` (which gives a reloaded module fresh
   function identities), are unaffected: each new identity gets its own
   cache entry, and old entries LRU-evict naturally.

   If you genuinely need to drop the per-function cache in-process:

   .. code-block:: pycon

      >>> from fleche.call import _profile

      >>> _profile.cache_clear()

.. note::

   Callables that aren't python-hashable (``__hash__ = None``, e.g. some
   instances with a custom ``__call__``) bypass the in-process cache
   transparently.  Correctness is preserved — the wrapper re-introspects
   on every call — but the cache-hit path is slower than for plain functions.

Usage with Decorated Methods
-----------------------------

.. note::

   When ``@fleche`` is applied to a method, the helper methods (`.call`, `.digest`, `.query`,
   `.load`, `.contains`, `.rerun`) do **not** automatically bind ``self``. Python's bound method
   objects delegate custom attribute lookups to the underlying function, so
   ``obj.method.query`` and ``MyClass.method.query`` return the same helper function.
   However, this helper is a plain function — not a bound method — so ``obj`` is not
   pre-applied; you must pass the instance explicitly as the first positional argument.

   For ``fleche`` to cache calls that include ``self``, the class must be
   *digestible* --- i.e. it must implement a ``__digest__`` method
   (see :doc:`/dev/custom_digests`).

   .. code-block:: pycon

      >>> from fleche import fleche
      >>> from fleche.digest import digest, Digest

      >>> class MyClass:
      ...     def __init__(self, id: int):
      ...         self.id = id
      ...
      ...     def __digest__(self) -> Digest:
      ...         return digest((type(self).__name__, self.id))
      ...
      ...     @fleche
      ...     def compute(self, x):
      ...         return x ** 2

      >>> obj = MyClass(id=1)

      >>> # Correct — pass self explicitly
      >>> obj.compute.query(obj, x=5)
      >>> obj.compute.contains(obj, x=5)
      >>> obj.compute.digest(obj, x=5)

      >>> # Also works as a keyword argument
      >>> obj.compute.query(self=obj, x=5)
