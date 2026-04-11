Parallel Execution
==================

Fleche-decorated functions work with Python's ``concurrent.futures`` executors
and other process-/thread-based parallelism libraries.  This page explains the
recommended patterns for each executor type.

.. contents:: On this page
   :local:
   :depth: 2

ThreadPoolExecutor
------------------

Use :class:`~fleche.BoundWrapper` with a ``with cache(...)`` block.
``BoundWrapper.bind(func)`` captures the active cache at bind time and
restores it on every call — including inside worker threads — so all tasks
write to the same store:

.. code-block:: python

   import concurrent.futures
   import fleche
   from fleche import BoundWrapper
   from fleche.caches import Cache
   from fleche.storage.memory import ValueMemory, CallMemory

   @fleche.fleche
   def compute(x):
       return x ** 2

   my_cache = Cache(ValueMemory({}), CallMemory({}))

   with fleche.cache(my_cache):
       with concurrent.futures.ThreadPoolExecutor() as executor:
           futures = [executor.submit(BoundWrapper.bind(compute), i) for i in range(4)]
           results = [f.result() for f in futures]  # all cached in my_cache

Passing a bound function around
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Because :class:`~fleche.BoundWrapper` is a regular picklable callable, you can
bind it once and pass it anywhere — to multiple executor pools, helper modules,
or across function calls.  The captured state travels with the callable:

.. code-block:: python

   with fleche.cache(my_cache):
       bound_compute = BoundWrapper.bind(compute)   # bind once

   # bound_compute carries my_cache — no cache context manager needed at the call site
   with concurrent.futures.ThreadPoolExecutor() as executor:
       futures = [executor.submit(bound_compute, i) for i in range(4)]
       results = [f.result() for f in futures]

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

.. code-block:: python

   import concurrent.futures
   import tempfile, os
   import fleche
   from fleche import BoundWrapper
   from fleche.caches import Cache
   from fleche.storage.pickle_file import ValuePickleFile, CallPickleFile

   @fleche.fleche
   def heavy_computation(x):
       return x ** 3

   with tempfile.TemporaryDirectory() as tmpdir:
       file_cache = Cache(
           ValuePickleFile.with_pickle(root=os.path.join(tmpdir, "values")),
           CallPickleFile.with_pickle(root=os.path.join(tmpdir, "calls")),
       )

       with fleche.cache(file_cache):
           with concurrent.futures.ProcessPoolExecutor() as executor:
               futures = [executor.submit(BoundWrapper.bind(heavy_computation), i)
                          for i in range(8)]
               results = [f.result() for f in futures]

       assert file_cache.contains(heavy_computation.digest(3))

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
- Use **file-** or **SQL-backed** storage with :class:`~fleche.BoundWrapper`.

.. code-block:: python

   from executorlib import SingleNodeExecutor

   with fleche.cache(file_cache):
       with SingleNodeExecutor() as executor:
           futures = [executor.submit(BoundWrapper.bind(heavy_computation), i)
                      for i in range(4)]
           results = [f.result() for f in futures]

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
     - ``BoundWrapper.bind(func)``
   * - ``ProcessPoolExecutor``
     - Yes
     - No (separate process)
     - File/SQL storage + ``BoundWrapper``
   * - ``executorlib.SingleNodeExecutor``
     - Yes
     - No (separate process)
     - File/SQL storage + ``BoundWrapper``
