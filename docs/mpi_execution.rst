MPI Execution
=============

:doc:`parallel_execution` covers executors that run a callable **once**.  MPI
launchers do not: ``executorlib``'s ``SingleNodeExecutor`` with
``resource_dict={"cores": N}`` — like ``SlurmClusterExecutor`` or
``FluxJobExecutor`` — starts ``N`` ranks and runs the *same* callable on each
of them, then gathers the per-rank return values into a list.

That changes what caching means, because a fleche cache key is built from the
function profile and the arguments and knows nothing about rank.  Every rank
computes the *same* key, so every rank is a candidate to hit the *same*
record — independently, and at a moment nobody coordinated.

.. contents:: On this page
   :local:
   :depth: 2

The shape of the problem
------------------------

Take the usual convention — rank 0 returns the answer, the other ranks return
``None`` — and decorate the kernel directly:

.. code-block:: python

   @fleche.fleche
   def mpi_sum(n):
       from mpi4py import MPI
       comm = MPI.COMM_WORLD
       rank = comm.Get_rank()
       local = sum(range(rank, n, comm.Get_size()))
       total = comm.reduce(local, op=MPI.SUM, root=0)   # collective!
       return total if rank == 0 else None

Submitted to a two-rank executor this behaves reasonably on the first run and
surprisingly on the second:

.. code-block:: pycon

   >>> exe.submit(bound_mpi_sum, 10).result()   # cold
   [45, None]
   >>> exe.submit(bound_mpi_sum, 10).result()   # warm
   [45, 45]

Nothing is corrupted, but the ``None`` that marked *"I am not the rank holding
the answer"* is gone.  Rank 1 never computed anything — it loaded rank 0's
record, because the record is not rank-specific.  Code downstream that tests
for ``None`` to decide which rank writes the output file will now have every
rank believe it owns the result.

The deadlock
------------

The return shape is the benign symptom.  The dangerous one is that **a cache
hit skips the function body**, and the body is where the collectives live.

Whether a given rank hits is decided by that rank's own view of the cache.  The
ranks are not synchronised, and their views are not guaranteed identical:

- workers on node-local scratch each have their own cache directory;
- a shared NFS mount may not have shown rank 0's write to rank 1 yet;
- a cache populated by an earlier run at a different rank count.

If rank 0 hits and rank 1 misses, rank 0 returns immediately while rank 1
blocks in a collective that rank 0 will never enter.  For a small message the
mismatch can pass unnoticed — the send fits in the eager buffer and the job
limps on with a silently wrong result.  Once the message is large enough to
need the rendezvous protocol, the job simply hangs:

.. code-block:: pycon

   >>> exe.submit(worker, 3).result()   # cold: fine
   [9.0, None]
   >>> exe.submit(worker, 3).result()   # warm, divergent views: hangs forever

.. danger::

   Never let a fleche cache lookup decide, per rank, whether to enter a
   collective.  Ranks that disagree will deadlock or corrupt the reduction.
   Whatever the decision is, every rank must reach the same one.

The recipe: agree before you branch
-----------------------------------

:func:`fleche.mpi.collective` makes one rank decide and broadcast the outcome,
so all ranks take the same branch — either nobody enters the body or everybody
does:

.. code-block:: python

   import fleche
   from fleche.mpi import collective

   @collective
   @fleche.fleche
   def mpi_sum(n):
       from mpi4py import MPI
       comm = MPI.COMM_WORLD
       rank = comm.Get_rank()
       local = sum(range(rank, n, comm.Get_size()))
       total = comm.reduce(local, op=MPI.SUM, root=0)
       return total if rank == 0 else None

Order matters: ``@collective`` goes **above** ``@fleche.fleche``, so it wraps
the fleche wrapper rather than the other way round.  It can also be applied at
the use site, ``collective(mpi_sum)(10)``, which is handy when the same kernel
is sometimes called serially.

The result is stable across runs, and no rank recomputes:

.. code-block:: pycon

   >>> exe.submit(worker, 10).result()   # cold
   [45, None]
   >>> exe.submit(worker, 10).result()   # warm
   [45, None]

What it actually does
^^^^^^^^^^^^^^^^^^^^^

On a communicator of size 1 the wrapper is transparent — the decorated
function is called unchanged, so the same code runs serially.  Otherwise:

#. Rank ``root`` (default ``0``) attempts ``func.fleche.load(*args)``.  A
   ``KeyError`` is a miss; any other failure is logged and also treated as a
   miss, because a broken lookup must never desynchronise the ranks.
#. That single boolean is broadcast.  **Every rank now branches on the same
   value**, whatever its own cache happens to contain.
#. **Hit** — no rank enters the body.  Rank ``root`` returns the cached value,
   the others return ``None``.
#. **Miss** — every rank runs the body, so the collectives inside it match up
   as they always did.  Rank ``root`` goes through the fleche wrapper and
   records its return value; the other ranks call the undecorated function and
   touch no cache at all.

Step 4 is why non-root ranks add no cache traffic: on a large job you do not
want ``N`` ranks writing argument values to a shared filesystem to store
results that are all ``None`` anyway.

Kernels where every rank returns the value
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

If the body ends in an ``Allreduce``/``allgather`` and every rank returns the
same answer, pass ``broadcast=True`` so a cache hit reproduces that too:

.. code-block:: python

   result = collective(mpi_sum, broadcast=True)(10)   # [45, 45] cold and warm

Caching the submission instead of the payload
---------------------------------------------

If you can restructure the call site, the simplest correct answer is to keep
fleche out of the ranks entirely and cache the *submission*:

.. code-block:: python

   def mpi_kernel(n):                       # plain, undecorated
       ...
       return total if rank == 0 else None

   with fleche.cache(my_cache), make_executor() as exe:

       @fleche.fleche
       def run(n):
           return exe.submit(mpi_kernel, n).result()

       run(10)   # cold: [45, None]
       run(10)   # warm: [45, None] -- no ranks are launched at all

fleche runs exactly once, in the serial parent, so rank divergence is not
possible by construction, and the cached value is the launcher's gathered list
verbatim.  On a hit no MPI processes are spawned — the whole allocation is
saved, not just the compute inside it.  The trade-off is that the ``None``
padding is stored alongside the answer, and that the cache key is the
*submission's* arguments, so a change in rank count does not invalidate it.

Prefer this when you own the submission site.  Reach for
:func:`~fleche.mpi.collective` when the decorated kernel is the thing that has
to run under MPI — for instance because it is called both serially and in
parallel, or because the decoration lives in library code you do not control.

``wrap_executor`` under MPI
---------------------------

:func:`~fleche.wrap_executor` short-circuits a cache hit in the parent, before
anything is submitted, which is the same win as caching the submission.  Note
one wrinkle before reaching for it here: the cold path returns the launcher's
gathered list, while the warm path returns the decorated function's own return
value.

.. code-block:: pycon

   >>> fleche.wrap_executor(exe)
   >>> exe.submit(mpi_sum, 10).result()   # cold: from the launcher
   [45, None]
   >>> exe.submit(mpi_sum, 10).result()   # warm: from the cache, unwrapped
   45

Callers that index into the result need to normalise the two.  It also does
nothing for the in-rank divergence problem — on a miss the ranks still each run
the decorated function — so combine it with :func:`~fleche.mpi.collective`
rather than treating it as an alternative.

Shared storage is still required
--------------------------------

Everything on this page assumes the ranks and the parent can see the same
records, which means file- or SQL-backed storage on a shared filesystem, as in
:doc:`parallel_execution`.  An in-memory cache is process-local, so every rank
would start empty and every run would be a cold run.

:func:`~fleche.mpi.collective` is what makes a *partially* shared view safe
rather than fatal — it does not remove the need to share.

Quick reference
---------------

.. list-table::
   :header-rows: 1
   :widths: 34 22 22 22

   * - Arrangement
     - Cold result
     - Warm result
     - Divergent views
   * - ``@fleche`` on the kernel, nothing else
     - ``[45, None]``
     - ``[45, 45]``
     - **deadlock**
   * - ``@collective`` + ``@fleche`` on the kernel
     - ``[45, None]``
     - ``[45, None]``
     - safe
   * - ``@collective(..., broadcast=True)``
     - ``[45, None]``
     - ``[45, 45]``
     - safe
   * - ``@fleche`` on the submitting function
     - ``[45, None]``
     - ``[45, None]``
     - not possible
   * - ``wrap_executor`` + ``@fleche`` kernel
     - ``[45, None]``
     - ``45``
     - **deadlock** on a miss

Limitations
-----------

- **Digest arguments are rejected.**  ``Digest`` arguments are expanded by the
  fleche wrapper against the active cache, which the non-root ranks
  deliberately bypass — they would receive the digest string instead of the
  value.  :func:`~fleche.mpi.collective` raises ``TypeError`` rather than
  running the body with mismatched arguments.  The check is local, so every
  rank raises identically.
- **``isolate=True`` does not combine with it.**  Non-root ranks call the
  undecorated function, so the per-call ``os.chdir`` into a temporary
  directory happens on the root rank only, leaving the ranks in different
  working directories.
- **Metadata is recorded for the root rank only.**  ``Runtime``,
  ``Environment`` and ``Git`` describe rank ``root``; the other ranks never
  reach the metadata hooks.
- **The rank count is not part of the key.**  A result cached from a 4-rank run
  is served to a 16-rank run of the same arguments.  That is usually what you
  want for a converged numerical result; add an explicit argument, or bump
  ``version=``, when it is not.
- **Cache stampede is unaddressed**, exactly as in :doc:`parallel_execution`:
  several jobs launched at once with the same arguments all miss and all
  compute.
