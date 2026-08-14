"""Calling fleche-decorated functions from every rank of an MPI communicator.

Motivation: MPI-parallel work submitted through a launcher like
``executorlib``'s ``SingleNodeExecutor(resource_dict={"cores": N})`` runs the
*same* callable once on every rank.  If that callable is decorated with
:func:`fleche.fleche`, every rank performs its own cache lookup — and the
lookup key is derived from the function profile and the arguments only, so it
carries **no notion of rank**.  Whether a rank hits or misses is therefore
decided independently on each rank, by whatever that rank's cache happens to
contain at that moment.

That independence is the problem.  A cache hit *skips the function body*, and
the body of an MPI kernel is exactly where the collectives live.  If rank 0
hits while rank 1 misses, rank 0 never enters ``Allreduce``/``Barrier``/… while
rank 1 blocks in it forever: the job deadlocks.  Divergent hit/miss decisions
are easy to reach in practice — node-local scratch directories, an NFS client
that has not yet seen rank 0's write, or simply a cache populated by an earlier
run at a different rank count.

Even when every rank *does* agree, the naive arrangement changes what the job
returns.  With the common "rank 0 returns the answer, the other ranks return
``None``" convention, the launcher gathers ``[answer, None, ...]`` on the first
(cold) run — but on the second run every rank hits the same shared record and
the gather becomes ``[answer, answer, ...]``, because the cached value is not
rank-specific.  Downstream code that keys off the ``None`` to decide which rank
owns the result then misfires.

:func:`collective` fixes both: one designated rank does the lookup and
broadcasts the outcome, so all ranks take the same branch — either nobody
enters the body or everybody does — and only the designated rank's return value
is ever recorded or replayed.

.. code-block:: python

   import fleche
   from fleche.mpi import collective

   @collective
   @fleche.fleche
   def simulate(n_steps):
       from mpi4py import MPI
       comm = MPI.COMM_WORLD
       ...                                   # collectives live here
       return answer if comm.Get_rank() == 0 else None

Requires the ``mpi`` extra (``pip install fleche[mpi]``).  See
:doc:`/mpi_execution` for the full recipe, including how to combine this with a
shared file-backed cache and with parent-side caching of the whole submission.
"""

import logging
from functools import wraps
from types import SimpleNamespace
from typing import Any, Callable, Optional

from pyiron_snippets.import_alarm import ImportAlarm

from .digest import Digest

logger = logging.getLogger("fleche.mpi")

with ImportAlarm(
    "fleche.mpi requires 'mpi4py' to be installed. "
    "Install it with `pip install fleche[mpi]`.",
    raise_exception=True,
) as mpi4py_alarm:
    # Deliberately the package, not ``mpi4py.MPI``: importing the extension
    # module calls ``MPI_Init``, and a serial parent that merely *builds* a
    # wrapper before handing it to a launcher must not join an MPI universe —
    # ``mpiexec`` children spawned from an already-initialised parent hang.
    # The real import happens inside the wrapper, on the ranks.
    import mpi4py  # noqa: F401


__all__ = ["collective"]


def _is_fleche_function(func: Any) -> bool:
    # Same test ``executor.wrap_executor`` uses: the decorator hangs its
    # helpers off a SimpleNamespace, so an unrelated ``.fleche`` attribute on
    # some other object does not pass for one.
    return isinstance(getattr(func, "fleche", None), SimpleNamespace)


def _digest_arguments(args: tuple, kwargs: dict) -> list[str]:
    """Names/positions of arguments passed as :class:`~fleche.digest.Digest`."""
    found = [f"#{i}" for i, v in enumerate(args) if isinstance(v, Digest)]
    found += [k for k, v in kwargs.items() if isinstance(v, Digest)]
    return found


@mpi4py_alarm
def collective(
    # Typed ``Any`` rather than ``Callable``: the argument is a fleche wrapper,
    # carrying the ``.fleche`` helper namespace and ``.__wrapped__`` that the
    # bare ``Callable`` protocol does not describe.  ``_is_fleche_function``
    # below does the checking a stricter annotation cannot.
    func: Any,
    *,
    comm: Optional[Any] = None,
    root: int = 0,
    broadcast: bool = False,
) -> Callable:
    """Make a fleche-decorated *func* safe to call from every rank of *comm*.

    Rank *root* owns the cache.  It performs the lookup and broadcasts whether
    it was a hit, so every rank takes the same branch:

    * **hit** — no rank enters the function body, so no collective inside it is
      entered by anyone.  Rank *root* returns the cached value; the other ranks
      return ``None`` (or the same value, with ``broadcast=True``).
    * **miss** — every rank runs the body, so the collectives inside it match
      up as they normally would.  Only rank *root* goes through the fleche
      wrapper and records its return value; the other ranks call the
      undecorated function and touch no cache at all.

    Use it either as a decorator directly above ``@fleche.fleche``::

        @collective
        @fleche.fleche
        def kernel(n): ...

    or as a plain call at the use site::

        result = collective(kernel)(n)

    On a communicator of size 1 the wrapper is transparent — *func* is called
    unchanged — so the same code runs serially without MPI in the loop.

    Args:
        func: a :func:`fleche.fleche`-decorated callable.
        comm: the communicator all ranks agree over.  Defaults to
            ``MPI.COMM_WORLD``, resolved **at call time** — ``mpi4py.MPI`` is
            not even imported until then, so a serial parent can build the
            wrapper and hand it to a launcher without joining an MPI universe
            itself.
        root: rank that owns the cache.  Defaults to ``0``.
        broadcast: if ``True``, a cached value is broadcast so every rank
            returns it.  Use this when the body returns the same value on every
            rank; leave it ``False`` for the "only rank *root* returns the
            answer" convention.

    Returns:
        A wrapper around *func* with the same signature.

    Raises:
        TypeError: if *func* is not fleche-decorated, or if the call passes a
            :class:`~fleche.digest.Digest` argument.  Digest arguments are
            expanded by the fleche wrapper against the active cache, which the
            non-root ranks deliberately bypass — they would receive the digest
            string instead of the value.  Pass the value itself instead.  The
            check is purely local, so every rank raises identically.

    Note:
        Because the non-root ranks call ``func.__wrapped__``, per-call decorator
        machinery — ``isolate=True``, metadata hooks — applies on rank *root*
        only.  ``isolate=True`` in particular would place the ranks in
        different working directories and should not be combined with this
        helper.
    """
    if not _is_fleche_function(func):
        raise TypeError(
            f"collective() expects a fleche-decorated function, got {func!r}. "
            "Apply @collective above @fleche.fleche, not below it."
        )

    @wraps(func)
    def wrapper(*args, **kwargs):
        if comm is None:
            from mpi4py import MPI

            active = MPI.COMM_WORLD
        else:
            active = comm
        if active.Get_size() == 1:
            # Nothing to agree on — keep the decorator fully in play.
            return func(*args, **kwargs)

        if digested := _digest_arguments(args, kwargs):
            raise TypeError(
                "collective() cannot take Digest arguments (got "
                f"{', '.join(digested)}): the non-root ranks bypass the fleche "
                "wrapper that would expand them.  Pass the value instead."
            )

        is_root = active.Get_rank() == root
        value, hit = None, False
        if is_root:
            try:
                value, hit = func.fleche.load(*args, **kwargs), True
            except KeyError:
                logger.debug("Cache miss on root rank %d", root)
            except Exception:
                # A broken lookup must not desynchronise the ranks: fall back
                # to recomputing, which every rank is about to agree to do.
                logger.warning("Cache lookup failed, recomputing", exc_info=True)

        if active.bcast(hit, root=root):
            return active.bcast(value, root=root) if broadcast else value

        if is_root:
            return func(*args, **kwargs)
        return func.__wrapped__(*args, **kwargs)

    return wrapper
