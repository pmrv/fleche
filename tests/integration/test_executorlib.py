"""
Integration tests: fleche-decorated functions submitted via executorlib's SingleNodeExecutor.

Key question: can fleche wrapper functions be called through a SingleNodeExecutor from executorlib,
and if so, does caching work?

Background: Context Var propagation
------------------------------------
fleche uses a ``contextvars.ContextVar`` (``state._CACHE``) to track which cache
is active.  Python's ContextVar semantics differ by execution model:

* **Same thread** – ContextVars are inherited.
* **ThreadPoolExecutor** – each task runs in a worker thread.  Whether context
  is propagated depends on Python version; the test_threadpool.py tests cover this.
* **ProcessPoolExecutor / executorlib workers** – worker processes are spawned
  as independent subprocesses with a fresh Python interpreter.  ContextVars
  revert to their *default* values.  In-memory state set in the parent is
  completely invisible.

executorlib's SingleNodeExecutor
---------------------------------
executorlib (https://github.com/pyiron/executorlib) is built on top of
``concurrent.futures`` and uses *process*-based workers.  Therefore:

* fleche-decorated functions **can** be called through SingleNodeExecutor and
  return correct results.
* However, an in-memory cache set via ``fleche.cache(...)`` in the parent process
  is **not visible** in the worker; results are NOT stored in the parent's cache.
* To share cached results across processes, use **file- or SQL-backed storage** and
  pass the shared path to the worker explicitly (see
  ``test_executorlib_file_backed_cache_shared``).
"""

import concurrent.futures
import tempfile
import pytest

import fleche
from fleche.caches import Cache
from fleche.storage.memory import Memory
from fleche.storage.pickle_file import PickleFile


@fleche.fleche
def double(x):
    return x * 2


def _worker_with_file_cache(x, values_dir, calls_dir):
    """Worker that sets up a shared file-backed cache and runs the fleche function."""
    values_storage = PickleFile.with_pickle(root=values_dir)
    calls_storage = PickleFile.with_pickle(root=calls_dir)
    worker_cache = Cache(values_storage, calls_storage)
    with fleche.cache(worker_cache):
        return double(x)


# ---------------------------------------------------------------------------
# Tests using concurrent.futures.ProcessPoolExecutor
# (identical process-isolation semantics to executorlib.SingleNodeExecutor)
# ---------------------------------------------------------------------------


def test_process_executor_returns_correct_result():
    """
    Fleche-decorated functions can be called through a ProcessPoolExecutor and
    return the correct result.
    """
    with concurrent.futures.ProcessPoolExecutor(max_workers=1) as executor:
        future = executor.submit(double, 21)
        result = future.result()

    assert result == 42


def test_process_executor_in_memory_cache_not_propagated():
    """
    An in-memory cache set in the parent is NOT visible in worker processes.

    Results computed in the worker are stored in the worker's ephemeral default
    cache and are NOT accessible from the parent's in-memory cache object.
    """
    mem = Memory({})
    cache = Cache(mem, mem)

    with fleche.cache(cache):
        with concurrent.futures.ProcessPoolExecutor(max_workers=1) as executor:
            future = executor.submit(double, 10)
            result = future.result()

    assert result == 20
    assert not cache.contains(double.digest(10)), (
        "In-memory cache is process-local; worker results are not visible to the parent."
    )


# ---------------------------------------------------------------------------
# Tests using executorlib.SingleNodeExecutor
# ---------------------------------------------------------------------------


def test_executorlib_returns_correct_result():
    """
    Fleche-decorated functions can be called through executorlib.SingleNodeExecutor
    and return the correct result.
    """
    try:
        from executorlib import SingleNodeExecutor
    except ImportError:
        pytest.skip("executorlib not installed")

    with SingleNodeExecutor() as executor:
        future = executor.submit(double, 21)
        result = future.result()

    assert result == 42, f"Expected 42, got {result}"


def test_executorlib_in_memory_cache_not_propagated():
    """
    An in-memory cache set in the parent is NOT visible inside executorlib workers.

    Results computed by the worker are not stored in the parent's in-memory cache.
    This is expected for any process-based executor.
    """
    try:
        from executorlib import SingleNodeExecutor
    except ImportError:
        pytest.skip("executorlib not installed")

    mem = Memory({})
    cache = Cache(mem, mem)

    with fleche.cache(cache):
        with SingleNodeExecutor() as executor:
            future = executor.submit(double, 99)
            result = future.result()

    assert result == 198, f"Expected 198, got {result}"
    assert not cache.contains(double.digest(99)), (
        "In-memory cache is process-local; executorlib worker results are not visible to the parent."
    )


def test_executorlib_file_backed_cache_shared():
    """
    Minimally working configuration: use file-backed storage so that worker
    results are persisted to a shared directory visible to the parent process.

    The worker explicitly sets up a PickleFile-backed cache pointing to the
    shared directory.  After the executor finishes, the parent can read back
    the cached result from the same directory.
    """
    try:
        from executorlib import SingleNodeExecutor
    except ImportError:
        pytest.skip("executorlib not installed")

    with tempfile.TemporaryDirectory() as tmpdir:
        values_dir = f"{tmpdir}/values"
        calls_dir = f"{tmpdir}/calls"

        # Parent-side cache pointing at the shared directories
        parent_values = PickleFile.with_pickle(root=values_dir)
        parent_calls = PickleFile.with_pickle(root=calls_dir)
        parent_cache = Cache(parent_values, parent_calls)

        with SingleNodeExecutor() as executor:
            future = executor.submit(_worker_with_file_cache, 21, values_dir, calls_dir)
            result = future.result()

        assert result == 42, f"Expected 42, got {result}"
        assert parent_cache.contains(double.digest(21)), (
            "With file-backed storage, results written by the worker process are "
            "visible to the parent via the shared filesystem path."
        )
