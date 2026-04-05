Parallel Execution
==================

Fleche-decorated functions work with Python's ``concurrent.futures`` executors
and other process-/thread-based parallelism libraries.  This page explains the
interaction between fleche's context-variable state and the different executor
models, and shows recommended patterns for each.

.. contents:: On this page
   :local:
   :depth: 2

Background: How Fleche Tracks State
------------------------------------

Fleche stores the active cache and metadata in Python
:mod:`contextvars` — specifically two ``ContextVar`` instances for the cache
and for metadata.  Context managers like ``fleche.cache(...)`` and
``fleche.meta(...)`` set these variables for the current context.

This design is inherently **thread-safe**: each logical execution context gets
its own value.  However, whether a new thread or process *inherits* the
parent's context depends on how it is spawned.

ThreadPoolExecutor
------------------

Threads spawned by :class:`concurrent.futures.ThreadPoolExecutor` do **not**
automatically inherit ``ContextVar`` values from the submitting thread.  A
fleche-decorated function submitted to a thread pool will therefore see the
*default* cache rather than one set via ``with fleche.cache(...)``.

Propagating context explicitly
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Use :func:`contextvars.copy_context` to snapshot the current context and
``ctx.run()`` to execute the function inside that snapshot:

.. code-block:: python

   import contextvars
   import concurrent.futures
   import fleche

   @fleche.fleche
   def compute(x):
       return x ** 2

   my_cache = fleche.Cache(values_storage, calls_storage)

   with fleche.cache(my_cache):
       ctx = contextvars.copy_context()
       with concurrent.futures.ThreadPoolExecutor() as executor:
           future = executor.submit(ctx.run, compute, 42)
           result = future.result()  # 1764, cached in my_cache

Results are written to ``my_cache`` because the worker thread runs inside the
copied context.

.. tip::

   If you submit many tasks, create **one** context snapshot and reuse it for
   every ``submit`` call — the snapshot is a lightweight, read-copy-on-write
   object.

ProcessPoolExecutor
-------------------

Worker processes are independent OS processes with their own Python
interpreter.  ``ContextVar`` values set in the parent are **never** visible in
workers — they always start from the default.

In-memory caches are therefore **not shared** across processes.  A result
computed in a worker is stored in the worker's own ephemeral cache and is lost
when the worker exits.

Using file- or SQL-backed storage
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

To share cached results between the parent and worker processes, point both
sides at the same **file-** or **SQL-backed** storage:

.. code-block:: python

   import concurrent.futures
   import fleche
   from fleche.caches import Cache
   from fleche.storage.pickle_file import PickleFile

   @fleche.fleche
   def heavy_computation(x):
       return x ** 3

   def worker(x, values_dir, calls_dir):
       """Each worker sets up a cache pointing at the shared directory."""
       values = PickleFile.with_pickle(root=values_dir)
       calls  = PickleFile.with_pickle(root=calls_dir)
       with fleche.cache(Cache(values, calls)):
           return heavy_computation(x)

   # Shared directories (could also be SQL connection strings)
   values_dir = "/tmp/fleche_values"
   calls_dir  = "/tmp/fleche_calls"

   with concurrent.futures.ProcessPoolExecutor() as executor:
       futures = [executor.submit(worker, i, values_dir, calls_dir)
                  for i in range(8)]
       results = [f.result() for f in futures]

   # Parent can now read the cached results
   parent_cache = Cache(
       PickleFile.with_pickle(root=values_dir),
       PickleFile.with_pickle(root=calls_dir),
   )
   assert parent_cache.contains(heavy_computation.digest(3))

Fleche's file-based storage uses lock files to coordinate concurrent writes, so
multiple workers can safely write to the same directory.

.. note::

   Fleche-decorated functions must be defined at **module level** so that they
   can be pickled by the executor.  Lambdas and locally-defined functions will
   raise a ``PicklingError``.

BoundWrapper — Freezing State for Workers
-----------------------------------------

:class:`fleche.state.BoundWrapper` captures the current cache and metadata into
a picklable callable, so workers automatically use the correct state without
manual setup:

.. code-block:: python

   import concurrent.futures
   from fleche.state import BoundWrapper
   import fleche

   @fleche.fleche
   def predict(x):
       return x * 2

   file_cache = fleche.Cache(values_storage, calls_storage)

   with fleche.cache(file_cache):
       bound_predict = BoundWrapper.bind(predict)

   with concurrent.futures.ProcessPoolExecutor() as executor:
       futures = [executor.submit(bound_predict, i) for i in range(4)]
       results = [f.result() for f in futures]

``BoundWrapper.bind(func)`` snapshots the active cache and metadata at bind
time.  When called — even in a different process after pickling — the bound
wrapper restores that state before invoking the function.

This also works for **plain functions that call fleche-decorated functions
internally**: the bound state propagates to all nested fleche calls.

.. code-block:: python

   @fleche.fleche
   def step_a(x):
       return x + 1

   def pipeline(x):
       """Plain function that uses fleche-decorated helpers."""
       return step_a(x) * 3

   with fleche.cache(file_cache):
       bound_pipeline = BoundWrapper.bind(pipeline)

   # In a worker process, step_a will use file_cache
   with concurrent.futures.ProcessPoolExecutor() as executor:
       future = executor.submit(bound_pipeline, 10)
       assert future.result() == 33  # (10 + 1) * 3

executorlib
-----------

`executorlib <https://executorlib.readthedocs.io/>`_ provides executors that
follow the same ``concurrent.futures`` interface but manage HPC resources
(SLURM, MPI, etc.).  Because ``executorlib.SingleNodeExecutor`` spawns worker
processes, the same rules as ``ProcessPoolExecutor`` apply:

- In-memory caches are **not** shared with workers.
- Use **file-** or **SQL-backed** storage and set it up explicitly in each
  worker, or use :class:`~fleche.state.BoundWrapper` with a file-backed cache.

.. code-block:: python

   from executorlib import SingleNodeExecutor

   with fleche.cache(file_cache):
       bound = BoundWrapper.bind(heavy_computation)

   with SingleNodeExecutor() as executor:
       future = executor.submit(bound, 42)
       result = future.result()

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
     - ``ctx.run()`` with ``copy_context()``
   * - ``ProcessPoolExecutor``
     - Yes
     - No (separate process)
     - File/SQL storage or ``BoundWrapper``
   * - ``executorlib.SingleNodeExecutor``
     - Yes
     - No (separate process)
     - File/SQL storage or ``BoundWrapper``
