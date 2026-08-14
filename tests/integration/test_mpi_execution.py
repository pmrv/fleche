"""
Integration tests: fleche caching when the decorated function runs once per MPI rank.

Launching MPI work through ``executorlib.SingleNodeExecutor`` with
``resource_dict={"cores": N}`` runs the submitted callable on *every* rank and
gathers the per-rank return values into a list.  A fleche-decorated callable
therefore performs N independent cache lookups whose key knows nothing about
rank, which has two consequences these tests pin down:

* **Return-shape flip** (``test_naive_*``) — under the usual "rank 0 returns
  the answer, the rest return ``None``" convention, the cold run gathers
  ``[answer, None, ...]`` but the warm run gathers ``[answer, answer, ...]``,
  because every rank hits the one shared, rank-agnostic record.
* **Divergence deadlock** (``test_recipe_survives_divergent_cache_views``) —
  if the ranks do not share a cache view, some hit and some miss.  A hit skips
  the body, so the ranks that hit never enter the collectives the ranks that
  missed are blocking in.  Without the fix this hangs; the test asserts it does
  not.

``fleche.mpi.collective`` fixes both by having one rank decide hit-vs-miss and
broadcasting that decision.  The recipe is documented in
``docs/mpi_execution.rst``.

Each scenario runs in its own subprocess with a hard timeout, so a regression
that reintroduces the deadlock fails the test instead of hanging the suite.
"""

import os
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest


_TIMEOUT = 180

try:
    import executorlib  # noqa: F401

    _has_executorlib = True
except ImportError:
    _has_executorlib = False

try:
    import mpi4py  # noqa: F401

    _has_mpi4py = True
except ImportError:
    _has_mpi4py = False


pytestmark = [
    pytest.mark.skipif(not _has_executorlib, reason="executorlib not installed"),
    pytest.mark.skipif(not _has_mpi4py, reason="mpi4py not installed"),
    pytest.mark.skipif(shutil.which("mpiexec") is None, reason="mpiexec not on PATH"),
]


# ---------------------------------------------------------------------------
# Subprocess driver
# ---------------------------------------------------------------------------
# MPI ranks are spawned by executorlib via mpiexec, so each scenario needs a
# fresh interpreter.  The body of every scenario is written to a temp script
# and run with a timeout; the script prints one ``KEY=value`` line per
# observation and the test parses them back.

_PREAMBLE = '''
import sys, tempfile
import fleche
from fleche.caches import Cache
from fleche.storage.pickle_file import ValuePickleFile, CallPickleFile
from executorlib import SingleNodeExecutor

ROOT = sys.argv[1]
CORES = int(sys.argv[2])


def make_cache(sub="shared"):
    return Cache(
        ValuePickleFile.with_pickle(root=f"{ROOT}/{sub}/values"),
        CallPickleFile.with_pickle(root=f"{ROOT}/{sub}/calls"),
    )


def make_executor():
    return SingleNodeExecutor(
        max_workers=1,
        resource_dict={"cores": CORES},
        openmpi_oversubscribe=True,
        hostname_localhost=True,
        block_allocation=True,
    )


def report(key, value):
    print(f"{key}={value!r}", flush=True)


@fleche.fleche
def mpi_sum(n):
    """Rank 0 returns the total, the other ranks return None."""
    from mpi4py import MPI
    comm = MPI.COMM_WORLD
    rank = comm.Get_rank()
    local = sum(range(rank, n, comm.Get_size()))
    total = comm.reduce(local, op=MPI.SUM, root=0)
    comm.Barrier()
    report(f"body_ran_on_rank_{rank}", True)
    return total if rank == 0 else None


@fleche.fleche
def mpi_heavy(n):
    """Same shape, but with a collective too large for eager buffering.

    A mismatched collective on a small message may go unnoticed; at this size
    the sender blocks in the rendezvous handshake, so a rank that skips the
    body deadlocks the ones that did not.
    """
    import numpy as np
    from mpi4py import MPI
    comm = MPI.COMM_WORLD
    rank = comm.Get_rank()
    buf = np.full(2_000_000, float(rank + 1))
    out = np.empty_like(buf)
    comm.Allreduce(buf, out, op=MPI.SUM)
    comm.Barrier()
    report(f"body_ran_on_rank_{rank}", True)
    return float(out[0]) * n if rank == 0 else None
'''


def _run_scenario(tmp_path: Path, body: str, cores: int = 2) -> dict:
    """Run *body* (appended to the preamble) and parse its ``KEY=value`` lines."""
    script = tmp_path / "scenario.py"
    script.write_text(_PREAMBLE + textwrap.dedent(body))

    env = dict(os.environ)
    # OpenMPI refuses to launch as root unless told to; harmless otherwise.
    env.setdefault("OMPI_ALLOW_RUN_AS_ROOT", "1")
    env.setdefault("OMPI_ALLOW_RUN_AS_ROOT_CONFIRM", "1")

    try:
        proc = subprocess.run(
            [sys.executable, str(script), str(tmp_path / "cache"), str(cores)],
            capture_output=True,
            text=True,
            timeout=_TIMEOUT,
            env=env,
        )
    except subprocess.TimeoutExpired as exc:
        pytest.fail(
            f"scenario deadlocked after {_TIMEOUT}s (ranks disagreed on "
            f"hit-vs-miss).\nstdout:\n{exc.stdout}"
        )

    if proc.returncode != 0:
        pytest.fail(
            f"scenario exited {proc.returncode}\n"
            f"stdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
        )

    observations = {}
    for line in proc.stdout.splitlines():
        if "=" in line and not line.startswith(" "):
            key, _, raw = line.partition("=")
            try:
                observations[key] = eval(raw)  # noqa: S307 - our own repr output
            except Exception:
                continue
    # Keys are overwritten by later runs, so keep the transcript around for
    # tests that need to *count* body executions rather than read the last one.
    observations["_body_runs"] = proc.stdout.count("body_ran_on_rank_")
    return observations


# ---------------------------------------------------------------------------
# The naive arrangement: @fleche straight on the MPI payload
# ---------------------------------------------------------------------------


def test_naive_cold_run_gathers_per_rank_returns(tmp_path):
    """Cold: every rank runs the body, so the gather keeps the None sentinels."""
    obs = _run_scenario(
        tmp_path,
        """
        with fleche.cache(make_cache()), make_executor() as exe:
            bound = fleche.BoundWrapper.bind(mpi_sum)
            report("cold", exe.submit(bound, 10).result())
        """,
    )
    assert obs["cold"] == [45, None]
    assert obs["body_ran_on_rank_0"] is True


def test_naive_warm_run_flips_the_return_shape(tmp_path):
    """Warm: the record is rank-agnostic, so *every* rank hits and returns it.

    This is the trap.  The job still produces the right answer in slot 0, but
    the ``None`` that marked "I am not the owning rank" is gone.
    """
    obs = _run_scenario(
        tmp_path,
        """
        with fleche.cache(make_cache()), make_executor() as exe:
            bound = fleche.BoundWrapper.bind(mpi_sum)
            report("cold", exe.submit(bound, 10).result())
            report("warm", exe.submit(bound, 10).result())
        """,
    )
    assert obs["cold"] == [45, None]
    assert obs["warm"] == [45, 45], "cached value is replayed on every rank"
    assert obs["_body_runs"] == 2, "the warm run does hit on both ranks"


# ---------------------------------------------------------------------------
# The recipe: fleche.mpi.collective
# ---------------------------------------------------------------------------


def test_collective_keeps_the_return_shape_stable(tmp_path):
    """Cold and warm agree: only the root rank ever reports a value."""
    obs = _run_scenario(
        tmp_path,
        """
        from fleche.mpi import collective

        def worker(n):
            with fleche.cache(make_cache()):
                return collective(mpi_sum)(n)

        with make_executor() as exe:
            report("cold", exe.submit(worker, 10).result())
            report("warm", exe.submit(worker, 10).result())
            report("warm2", exe.submit(worker, 10).result())
        """,
    )
    assert obs["cold"] == [45, None]
    assert obs["warm"] == [45, None]
    assert obs["warm2"] == [45, None]


def test_collective_skips_the_body_on_a_hit(tmp_path):
    """A warm run must not re-enter the body on *any* rank.

    This is what makes the cache worth having: the shape being stable is not
    enough on its own, the work has to actually be skipped.
    """
    obs = _run_scenario(
        tmp_path,
        """
        from fleche.mpi import collective

        def worker(n):
            with fleche.cache(make_cache()):
                return collective(mpi_sum)(n)

        with make_executor() as exe:
            report("cold", exe.submit(worker, 10).result())
            report("warm", exe.submit(worker, 10).result())
            report("warm2", exe.submit(worker, 10).result())
        """,
    )
    assert obs["cold"] == [45, None]
    assert obs["warm"] == [45, None]
    # The body announces itself once per rank it runs on.  Two ranks, one cold
    # run, two warm hits => exactly two executions in total.
    assert obs["_body_runs"] == 2


def test_collective_recomputes_for_new_arguments(tmp_path):
    """Caching must not swallow a genuinely different call."""
    obs = _run_scenario(
        tmp_path,
        """
        from fleche.mpi import collective

        def worker(n):
            with fleche.cache(make_cache()):
                return collective(mpi_sum)(n)

        with make_executor() as exe:
            report("first", exe.submit(worker, 10).result())
            report("second", exe.submit(worker, 20).result())
            report("first_again", exe.submit(worker, 10).result())
        """,
    )
    assert obs["first"] == [45, None]
    assert obs["second"] == [190, None]
    assert obs["first_again"] == [45, None]


def test_recipe_survives_divergent_cache_views(tmp_path):
    """The headline guarantee: ranks that disagree must not deadlock.

    Each rank gets its own cache root, so rank 0 hits while rank 1 has never
    stored anything (its return was ``None``).  Without the broadcast the
    ``Allreduce`` in ``mpi_heavy`` hangs and this test times out.
    """
    obs = _run_scenario(
        tmp_path,
        """
        from fleche.mpi import collective

        def worker(n):
            from mpi4py import MPI
            rank = MPI.COMM_WORLD.Get_rank()
            with fleche.cache(make_cache(sub=f"rank{rank}")):   # NOT shared
                return collective(mpi_heavy)(n)

        with make_executor() as exe:
            report("cold", exe.submit(worker, 3).result())
            report("warm", exe.submit(worker, 3).result())
        """,
    )
    assert obs["cold"] == [9.0, None]
    assert obs["warm"] == [9.0, None]


def test_collective_broadcast_gives_every_rank_the_value(tmp_path):
    """``broadcast=True`` suits kernels whose ranks all return the same value."""
    obs = _run_scenario(
        tmp_path,
        """
        from fleche.mpi import collective

        def worker(n):
            with fleche.cache(make_cache()):
                return collective(mpi_sum, broadcast=True)(n)

        with make_executor() as exe:
            report("cold", exe.submit(worker, 10).result())
            report("warm", exe.submit(worker, 10).result())
        """,
    )
    assert obs["cold"] == [45, None]
    assert obs["warm"] == [45, 45]


def test_collective_at_three_ranks(tmp_path):
    """The agreement broadcast is not a two-rank special case."""
    obs = _run_scenario(
        tmp_path,
        """
        from fleche.mpi import collective

        def worker(n):
            with fleche.cache(make_cache()):
                return collective(mpi_sum)(n)

        with make_executor() as exe:
            report("cold", exe.submit(worker, 10).result())
            report("warm", exe.submit(worker, 10).result())
        """,
        cores=3,
    )
    assert obs["cold"] == [45, None, None]
    assert obs["warm"] == [45, None, None]


# ---------------------------------------------------------------------------
# Caching the submission instead of the payload
# ---------------------------------------------------------------------------


def test_parent_side_caching_never_spawns_ranks_on_a_hit(tmp_path):
    """Decorating the submission site keeps fleche out of the ranks entirely.

    The cached value is the launcher's gathered list, so the return shape is
    identical on both runs and no rank-level divergence is possible.
    """
    obs = _run_scenario(
        tmp_path,
        """
        def mpi_kernel(n):
            from mpi4py import MPI
            comm = MPI.COMM_WORLD
            rank = comm.Get_rank()
            local = sum(range(rank, n, comm.Get_size()))
            total = comm.reduce(local, op=MPI.SUM, root=0)
            report(f"body_ran_on_rank_{rank}", True)
            return total if rank == 0 else None

        with fleche.cache(make_cache()), make_executor() as exe:

            @fleche.fleche
            def run(n):
                return exe.submit(mpi_kernel, n).result()

            report("cold", run(10))
            report("warm", run(10))
        """,
    )
    assert obs["cold"] == [45, None]
    assert obs["warm"] == [45, None], "the gathered list is cached verbatim"


def test_wrap_executor_short_circuits_but_changes_the_return_type(tmp_path):
    """``wrap_executor`` serves the hit from the parent -- unwrapped.

    Worth knowing before reaching for it here: the cold run returns the
    launcher's gathered *list*, the warm run returns the decorated function's
    own return value.  Callers that index into the result need to normalise.
    """
    obs = _run_scenario(
        tmp_path,
        """
        with fleche.cache(make_cache()), make_executor() as exe:
            fleche.wrap_executor(exe)
            report("cold", exe.submit(mpi_sum, 10).result())
            report("warm", exe.submit(mpi_sum, 10).result())
        """,
    )
    assert obs["cold"] == [45, None]
    assert obs["warm"] == 45


# ---------------------------------------------------------------------------
# Unit-ish guards that need no MPI launch
# ---------------------------------------------------------------------------


def test_collective_rejects_an_undecorated_function():
    from fleche.mpi import collective

    with pytest.raises(TypeError, match="fleche-decorated"):
        collective(lambda x: x)


def test_collective_rejects_digest_arguments():
    import fleche
    from fleche.digest import Digest
    from fleche.mpi import collective

    @fleche.fleche
    def f(x):
        return x

    # Size-1 COMM_WORLD is transparent, so force a stub communicator to reach
    # the guard.
    class _Comm:
        def Get_size(self):
            return 2

        def Get_rank(self):
            return 1

    with pytest.raises(TypeError, match="Digest arguments"):
        collective(f, comm=_Comm())(Digest("a" * 64))


def test_collective_is_transparent_on_a_single_rank():
    import fleche
    from fleche.caches import Cache
    from fleche.mpi import collective
    from fleche.storage.memory import ValueMemory, CallMemory

    @fleche.fleche
    def f(x):
        return x * 2

    class _Comm:
        def Get_size(self):
            return 1

    cache = Cache(ValueMemory({}), CallMemory({}))
    with fleche.cache(cache):
        assert collective(f, comm=_Comm())(21) == 42
        assert cache.contains(f.fleche.digest(21))
