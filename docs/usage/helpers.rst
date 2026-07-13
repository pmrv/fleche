Decorator Helpers
=================

Functions decorated with ``@fleche`` are enhanced with several helper methods that allow for manual interaction with the cache and inspection of function calls.

Helper Methods
--------------

The following methods are added to the decorated function:

``.call(*args, **kwargs)``
~~~~~~~~~~~~~~~~~~~~~~~~~~

Returns a ``Call`` object corresponding to the provided arguments. This object contains metadata about the call, such as the function name, arguments, and version, but does not execute the function.

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
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Returns matching cached calls from the active cache. Any argument passed as ``None`` acts as a wildcard, matching any stored value for that parameter. The ``metadata`` keyword argument accepts a dictionary of metadata tags to further filter results (e.g., ``metadata={"tags": {"project": "alpha"}}``).

.. warning::

   If the decorated function has a parameter named ``metadata``, that parameter
   is shadowed by ``.query()``'s own ``metadata=`` keyword and **cannot** be
   passed as a keyword argument.  Pass it positionally instead::

      # function signature: def fetch(user_id, metadata):
      fetch.query(123, "v1")           # positional — works
      fetch.query(user_id=123, metadata="v1")  # shadowed — 'metadata' is
                                               # interpreted as the filter dict

   ``fleche`` logs a ``WARNING`` when this situation is detected.

See :doc:`query` for a detailed guide on querying cached calls.

``.rerun(*args, **kwargs)``
~~~~~~~~~~~~~~~~~~~~~~~~~~~

Forces the function to re-execute, even if its result is already present in the cache, and saves the newly computed result to the cache (unless the result is ``None``, in which case any prior cached result is evicted instead — see :ref:`none-not-cached`). This forces reevaluation recursively for any nested ``@fleche`` calls as well.

``.bind(*args, **kwargs)``
~~~~~~~~~~~~~~~~~~~~~~~~~~

Returns a :class:`~fleche.state.BoundWrapper` that captures the currently active cache and metadata at the moment of the call. The bound wrapper is a plain callable — it does not carry the ``fleche`` helper namespace.

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

   >>> # Pre-apply arguments
   >>> with cache("memory"):
   ...     bound_partial = add.bind(1, 2)
   ...     result = bound_partial()   # equivalent to add(1, 2) in the frozen context
   ...     assert result == 3

See :class:`~fleche.state.BoundWrapper` for the full API, including pickling support.

See :ref:`none-not-cached` for the behavior when a decorated function's result is ``None``, including for ``.rerun()``.

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
- the digest of ``func.__code__`` (included in cache keys only when ``hash_code=True``; the default is ``False``)
- ``(qualname, module, version)`` extracted via
  :class:`pyiron_snippets.versions.VersionInfo` — ``module`` and ``version``
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
