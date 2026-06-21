Parallel Execution
==================

Fleche-decorated functions work with Python's ``concurrent.futures`` executors
and other process-/thread-based parallelism libraries.  This page explains the
recommended patterns for each executor type.

Three complementary APIs cover the common cases:

- :class:`~fleche.BoundWrapper` — freeze the active cache and metadata into a
  picklable callable that a worker can invoke without any further setup.  Use
  when you own the submission site and want explicit control.
- **Future pass-through** — a fleche-decorated function that internally
  returns a :class:`~concurrent.futures.Future` is cached automatically when
  the future completes.  Use when the decorated function *is* the one that
  submits work.
- :func:`~fleche.wrap_executor` — a one-line wrapper around an executor
  instance that transparently binds fleche-decorated functions on ``submit``
  **and** short-circuits cache hits without ever touching the executor.  Use
  when you want the most compact call site, or to avoid submit/serialise
  overhead on cached inputs.

.. contents:: On this page
   :local:
   :depth: 2

ThreadPoolExecutor
------------------

For the most compact call site, use :func:`~fleche.wrap_executor` — it patches
the executor's ``submit`` once and then handles any fleche-decorated function
automatically, serving cache hits from a pre-completed
:class:`~concurrent.futures.Future` without ever submitting a task:

.. code-block:: pycon

   >>> import concurrent.futures
   >>> import fleche
   >>> from fleche.caches import Cache
   >>> from fleche.storage.memory import ValueMemory, CallMemory

   >>> @fleche.fleche
   ... def compute(x):
   ...     return x ** 2

   >>> my_cache = Cache(ValueMemory({}), CallMemory({}))

   >>> with fleche.cache(my_cache):
   ...     with concurrent.futures.ThreadPoolExecutor() as executor:
   ...         fleche.wrap_executor(executor)
   ...         futures = [executor.submit(compute, i) for i in range(4)]
   ...         results = [f.result() for f in futures]  # all cached in my_cache

Alternatively, use :class:`~fleche.BoundWrapper` when you need explicit
control over which callable is submitted — for example, to share a single
bound callable across multiple pools or helper modules.
``BoundWrapper.bind(func)`` captures the active cache at bind time and
restores it on every call — including inside worker threads — so all tasks
write to the same store:

.. code-block:: pycon

   >>> import concurrent.futures
   >>> import fleche
   >>> from fleche import BoundWrapper
   >>> from fleche.caches import Cache
   >>> from fleche.storage.memory import ValueMemory, CallMemory

   >>> @fleche.fleche
   ... def compute(x):
   ...     return x ** 2

   >>> my_cache = Cache(ValueMemory({}), CallMemory({}))

   >>> with fleche.cache(my_cache):
   ...     with concurrent.futures.ThreadPoolExecutor() as executor:
   ...         futures = [executor.submit(BoundWrapper.bind(compute), i) for i in range(4)]
   ...         results = [f.result() for f in futures]  # all cached in my_cache

Passing a bound function around
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Because :class:`~fleche.BoundWrapper` is a regular picklable callable, you can
bind it once and pass it anywhere — to multiple executor pools, helper modules,
or across function calls.  The captured state travels with the callable:

.. code-block:: pycon

   >>> with fleche.cache(my_cache):
   ...     bound_compute = BoundWrapper.bind(compute)   # bind once

   >>> # bound_compute carries my_cache — no cache context manager needed at the call site
   >>> with concurrent.futures.ThreadPoolExecutor() as executor:
   ...     futures = [executor.submit(bound_compute, i) for i in range(4)]
   ...     results = [f.result() for f in futures]

ProcessPoolExecutor
-------------------

Worker processes are independent OS processes with their own Python
interpreter.  In-memory caches are **not shared** across processes — a result
computed in a worker is stored in the worker's own ephemeral cache and is lost
when the worker exits.

To share cached results, point both the parent and workers at the same
**file-** or **SQL-backed** storage.  ``BoundWrapper.bind(func)`` embeds the
cache configuration into the callable so no manual worker-wrapper function is
needed:

.. code-block:: pycon

   >>> import concurrent.futures
   >>> import tempfile, os
   >>> import fleche
   >>> from fleche import BoundWrapper
   >>> from fleche.caches import Cache
   >>> from fleche.storage.pickle_file import ValuePickleFile, CallPickleFile

   >>> @fleche.fleche
   ... def heavy_computation(x):
   ...     return x ** 3

   >>> with tempfile.TemporaryDirectory() as tmpdir:
   ...     file_cache = Cache(
   ...         ValuePickleFile.with_pickle(root=os.path.join(tmpdir, "values")),
   ...         CallPickleFile.with_pickle(root=os.path.join(tmpdir, "calls")),
   ...     )
   ...
   ...     with fleche.cache(file_cache):
   ...         with concurrent.futures.ProcessPoolExecutor() as executor:
   ...             futures = [executor.submit(BoundWrapper.bind(heavy_computation), i)
   ...                        for i in range(8)]
   ...             results = [f.result() for f in futures]
   ...
   ...     assert file_cache.contains(heavy_computation.digest(3))

Fleche's file-based storage uses lock files to coordinate concurrent writes, so
multiple workers can safely write to the same directory.

.. note::

   With the standard-library ``ProcessPoolExecutor`` (which uses ``pickle``),
   fleche-decorated functions must be defined at **module level**.  Lambdas and
   locally-defined functions will raise a ``PicklingError``.

   Third-party executor libraries that use ``dill`` or ``cloudpickle`` for
   serialisation — such as `executorlib <https://executorlib.readthedocs.io/>`_
   or `parsl <https://parsl-project.org/>`_ — do not have this restriction and
   can submit locally-defined functions directly.

BoundWrapper — Freezing State for Workers
-----------------------------------------

:class:`fleche.BoundWrapper` captures the current cache and metadata into
a picklable callable, so workers automatically use the correct state without
manual setup.

This also works for **plain functions that call fleche-decorated functions
internally**: the bound state propagates to all nested fleche calls.

.. code-block:: pycon

   >>> @fleche.fleche
   ... def step_a(x):
   ...     return x + 1

   >>> def pipeline(x):
   ...     """Plain function that uses fleche-decorated helpers."""
   ...     return step_a(x) * 3

   >>> with fleche.cache(file_cache):
   ...     bound_pipeline = BoundWrapper.bind(pipeline)

   >>> # In a worker process, step_a will use file_cache
   >>> with concurrent.futures.ProcessPoolExecutor() as executor:
   ...     future = executor.submit(bound_pipeline, 10)
   ...     assert future.result() == 33  # (10 + 1) * 3

executorlib
-----------

`executorlib <https://executorlib.readthedocs.io/>`_ provides executors that
follow the same ``concurrent.futures`` interface but manage HPC resources
(SLURM, MPI, etc.).  Because ``executorlib.SingleNodeExecutor`` spawns worker
processes, the same rules as ``ProcessPoolExecutor`` apply:

- In-memory caches are **not** shared with workers.
- Use **file-** or **SQL-backed** storage with :class:`~fleche.BoundWrapper`.

.. code-block:: pycon

   >>> # file_cache and heavy_computation as set up in the ProcessPoolExecutor example above
   >>> import fleche
   >>> from fleche import BoundWrapper
   >>> from executorlib import SingleNodeExecutor

   >>> with fleche.cache(file_cache):
   ...     with SingleNodeExecutor() as executor:
   ...         futures = [executor.submit(BoundWrapper.bind(heavy_computation), i)
   ...                    for i in range(4)]
   ...         results = [f.result() for f in futures]

Future Pass-Through — Caching Async-style Results
--------------------------------------------------

As an alternative to :class:`~fleche.BoundWrapper`, you can write a
fleche-decorated function that itself submits work to an executor and returns
the resulting :class:`~concurrent.futures.Future`.  Fleche detects the
``Future`` return value, passes it through to the caller unchanged, and
automatically caches the result once the future completes:

.. code-block:: pycon

   >>> import concurrent.futures
   >>> import fleche
   >>> from fleche.caches import Cache
   >>> from fleche.storage.memory import ValueMemory, CallMemory

   >>> _executor = concurrent.futures.ThreadPoolExecutor()

   >>> @fleche.fleche
   ... def compute(x):
   ...     """Submits work and returns a Future — fleche caches on completion."""
   ...     return _executor.submit(lambda: x ** 2)

   >>> my_cache = Cache(ValueMemory({}), CallMemory({}))

   >>> with fleche.cache(my_cache):
   ...     future = compute(4)   # returns the Future immediately
   ...     result = future.result()   # 16, and the result is now cached

On the next call, ``compute(4)`` returns the cached value directly (no
``Future`` is created).

.. note::

   When a decorated function with future pass-through is called and a cached
   value already exists, the function is **not** invoked and no ``Future`` is
   created — the cached result is returned directly.

``wrap_executor`` — Transparent Submit Interception
---------------------------------------------------

:func:`fleche.wrap_executor` monkey-patches ``executor.submit`` on an existing
executor **instance** (no subclassing — callers pass us instances of
third-party executors) so that fleche-decorated functions are handled
automatically:

- Non-fleche callables pass straight through to the original ``submit``.
- Cache hits are served from an already-completed
  :class:`~concurrent.futures.Future` without ever touching the executor,
  avoiding submit/serialise overhead on cached inputs.
- Cache misses are bound via :meth:`~fleche.BoundWrapper.bind` so the parent's
  cache and metadata travel with the call into the worker.

.. code-block:: pycon

   >>> import concurrent.futures, tempfile, os
   >>> import fleche
   >>> from fleche.caches import Cache
   >>> from fleche.storage.pickle_file import ValuePickleFile, CallPickleFile

   >>> @fleche.fleche
   ... def heavy_computation(x):
   ...     return x ** 3

   >>> with tempfile.TemporaryDirectory() as tmpdir:
   ...     file_cache = Cache(
   ...         ValuePickleFile.with_pickle(root=os.path.join(tmpdir, "values")),
   ...         CallPickleFile.with_pickle(root=os.path.join(tmpdir, "calls")),
   ...     )
   ...
   ...     with fleche.cache(file_cache):
   ...         with concurrent.futures.ProcessPoolExecutor() as executor:
   ...             fleche.wrap_executor(executor)             # patch once
   ...
   ...             # Submit exactly as you would a plain function.
   ...             futures = [executor.submit(heavy_computation, i) for i in range(8)]
   ...             results = [f.result() for f in futures]
   ...
   ...         # A second round with the same inputs never enters the worker pool:
   ...         with concurrent.futures.ProcessPoolExecutor() as executor:
   ...             fleche.wrap_executor(executor)
   ...             fut = executor.submit(heavy_computation, 3)
   ...             assert fut.done()                          # already-completed future
   ...             assert fut.result() == 27

Executor-specific keyword arguments
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Some executors (e.g. `executorlib
<https://executorlib.readthedocs.io/>`_'s ``resource_dict``, dask's
``resources=``/``key=``) define their own keyword-only parameters on
``submit``.  :func:`~fleche.wrap_executor` introspects the signature with
:func:`inspect.signature` and splits those off automatically — they are
forwarded to ``submit`` while the rest are bound as part of the callable's
payload:

.. code-block:: pycon

   >>> # file_cache and heavy_computation as set up in the wrap_executor example above
   >>> from executorlib import SingleNodeExecutor

   >>> with fleche.cache(file_cache):
   ...     with SingleNodeExecutor() as executor:
   ...         fleche.wrap_executor(executor)
   ...         future = executor.submit(
   ...             heavy_computation, 5,
   ...             resource_dict={"cores": 4},   # goes to SingleNodeExecutor.submit
   ...         )
   ...         assert future.result() == 125

.. note::

   :func:`~fleche.wrap_executor` mutates the instance it is given; it does
   not return a proxy.  The call is idempotent: wrapping an already-wrapped
   executor a second time is a no-op.

When to prefer each pattern
---------------------------

.. list-table::
   :header-rows: 1
   :widths: 22 26 26 26

   * -
     - :class:`~fleche.BoundWrapper`
     - Future pass-through
     - :func:`~fleche.wrap_executor`
   * - Who owns the executor?
     - Caller
     - The decorated function
     - Caller
   * - Call-site change
     - Wrap callable: ``executor.submit(BoundWrapper.bind(func), ...)``
     - None (decorated function returns a ``Future``)
     - Patch executor once, then ``executor.submit(func, ...)``
   * - Cache hit behaviour
     - Always submits; worker does the cache lookup
     - Returns cached result directly (no ``Future`` created)
     - Returns an already-completed ``Future`` without contacting the worker
   * - Works across processes
     - Yes, with file/SQL storage
     - Yes, if the wrapping function owns the executor
     - Yes, with file/SQL storage
   * - Best for
     - Fine-grained control; sharing a bound callable across modules
     - Wrapping expensive async-style code inside a decorated helper
     - Transparently caching existing executor-based pipelines

The ``isolate`` Flag
--------------------

The ``@fleche(isolate=True)`` option creates a temporary working directory for
each function invocation to prevent file-system conflicts when the wrapped
function writes to the current directory.  This is useful for parallel
execution of functions that produce side-effect files.

.. warning::

   ``os.chdir()`` is **process-wide and not thread-safe**.  The ``isolate``
   flag should only be combined with process-based executors, not with
   ``ThreadPoolExecutor``.


Quick Reference
---------------

.. list-table::
   :header-rows: 1
   :widths: 30 15 25 30

   * - Executor
     - Works?
     - Context inherited?
     - Recommended pattern
   * - ``ThreadPoolExecutor``
     - Yes
     - No (manual)
     - :func:`~fleche.wrap_executor` (simplest), or ``BoundWrapper.bind(func)``,
       or future pass-through
   * - ``ProcessPoolExecutor``
     - Yes
     - No (separate process)
     - File/SQL storage + :func:`~fleche.wrap_executor` (or ``BoundWrapper``)
   * - ``executorlib.SingleNodeExecutor``
     - Yes
     - No (separate process)
     - File/SQL storage + :func:`~fleche.wrap_executor` (or ``BoundWrapper``)
   * - Function returns ``Future`` directly
     - Yes
     - Yes (same thread/context)
     - Future pass-through (function returns its own ``Future``)

Known Limitations
-----------------

Cache Stampede (Thundering Herd)
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Fleche does **not** protect against cache stampedes.  When multiple workers
(threads or processes) call the same fleche-decorated function with identical
arguments at the same time and the result is not yet cached, all of them will
experience a cache miss simultaneously.  Each worker then independently
computes the function and writes the result — wasting redundant work and
potentially producing inconsistent call metadata (e.g. ``Runtime`` values will
differ between the duplicate records).

The root cause is that there is no reservation mechanism between the cache
miss check and the cache write in ``wrapper.py``.  A correct fix would require
pre-allocating a "pending" slot in the cache so that other workers can detect
the in-flight computation and wait, rather than starting their own.
Implementing this correctly is non-trivial: it requires key-scoped locking,
timeout handling for stale allocations (e.g. if the computing worker crashes),
and cross-process coordination for file- and SQL-backed stores.  This is
currently out of scope.

.. warning::

   If you submit many workers with the same arguments before the first result
   is cached, all workers will compute the function.  The last writer wins for
   the stored value, but **no data is lost or corrupted** — subsequent calls
   will hit the cache normally.

**Practical workarounds:**

- Pre-warm the cache sequentially before launching parallel workers.
- Partition work so each worker handles a disjoint set of arguments.
