"""
Integration tests: fleche-decorated functions submitted via thread and process-based executors.

Thread-based execution (ThreadPoolExecutor)
--------------------------------------------
fleche uses a ``contextvars.ContextVar`` (``state._CACHE``) to track which cache is active.
In Python, ContextVar values are NOT automatically inherited by threads spawned via
ThreadPoolExecutor. The tests below document both the failure case and the workaround
(explicit context propagation via ``contextvars.copy_context()``).

``BoundWrapper.bind(func)`` is the recommended alternative: it captures the current cache
and metadata state at bind time and restores it on each call, without requiring
``ctx.run`` at the call site.

Process-based execution (ProcessPoolExecutor / executorlib SingleNodeExecutor)
-------------------------------------------------------------------------------
Worker processes are spawned as independent subprocesses with a fresh Python interpreter.
ContextVars revert to their *default* values — in-memory state set in the parent is
completely invisible to workers.

* fleche-decorated functions **can** be called through ProcessPoolExecutor / executorlib and
  return correct results.
* However, an in-memory cache set via ``fleche.cache(...)`` in the parent process
  is **not visible** in the worker; results are NOT stored in the parent's cache.
* To share cached results across processes use **file- or SQL-backed storage**.
  ``BoundWrapper.bind(func)`` (called while the file cache is active) embeds the cache
  configuration into the callable itself, eliminating the need for a separate worker
  wrapper function (see ``test_process_executor_bound_wrapper`` and
  ``test_executorlib_bound_wrapper``).
"""

import concurrent.futures
import contextvars
import tempfile
import pytest

import fleche
from fleche import BoundWrapper
from fleche.caches import Cache
from fleche.storage.memory import ValueMemory, CallMemory
from fleche.storage.pickle_file import ValuePickleFile, CallPickleFile

try:
    import executorlib  # noqa: F401
    _executorlib_available = True
except ImportError:
    _executorlib_available = False

_skip_no_executorlib = pytest.mark.skipif(
    not _executorlib_available, reason="executorlib not installed"
)


@fleche.fleche
def my_func(x):
    return x + 1


@fleche.fleche
def double(x):
    return x * 2


def _worker_with_file_cache(x, values_dir, calls_dir):
    """Worker that sets up a shared file-backed cache and runs the fleche function."""
    values_storage = ValuePickleFile.with_pickle(root=values_dir)
    calls_storage = CallPickleFile.with_pickle(root=calls_dir)
    worker_cache = Cache(values_storage, calls_storage)
    with fleche.cache(worker_cache):
        return double(x)


# ---------------------------------------------------------------------------
# ThreadPoolExecutor tests
# ---------------------------------------------------------------------------


def test_threadpool_inheritance_failure():
    """
    Demonstrate that standard fleche.cache() context manager
    does not propagate to ThreadPoolExecutor in this environment.
    """
    cache1 = Cache(ValueMemory({}), CallMemory({}))

    with fleche.cache(cache1):
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            # We expect this NOT to be in cache1 if inheritance fails
            future = executor.submit(my_func, 100)
            future.result()

            assert not cache1.contains(my_func.digest(100))


def test_threadpool_explicit_context_propagation():
    """
    Demonstrate that explicit context propagation works.
    """
    cache1 = Cache(ValueMemory({}), CallMemory({}))

    with fleche.cache(cache1):
        ctx = contextvars.copy_context()
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(ctx.run, my_func, 200)
            future.result()

            assert cache1.contains(my_func.digest(200))


# ---------------------------------------------------------------------------
# ProcessPoolExecutor tests
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
    cache = Cache(ValueMemory({}), CallMemory({}))

    with fleche.cache(cache):
        with concurrent.futures.ProcessPoolExecutor(max_workers=1) as executor:
            future = executor.submit(double, 10)
            result = future.result()

    assert result == 20
    assert not cache.contains(double.digest(10)), (
        "In-memory cache is process-local; worker results are not visible to the parent."
    )


# ---------------------------------------------------------------------------
# executorlib.SingleNodeExecutor tests
# ---------------------------------------------------------------------------


@_skip_no_executorlib
def test_executorlib_returns_correct_result():
    """
    Fleche-decorated functions can be called through executorlib.SingleNodeExecutor
    and return the correct result.
    """
    from executorlib import SingleNodeExecutor

    with SingleNodeExecutor() as executor:
        future = executor.submit(double, 21)
        result = future.result()

    assert result == 42, f"Expected 42, got {result}"


@_skip_no_executorlib
def test_executorlib_file_backed_cache_shared():
    """
    Minimally working configuration: use file-backed storage so that worker
    results are persisted to a shared directory visible to the parent process.

    The worker explicitly sets up a PickleFile-backed cache pointing to the
    shared directory.  After the executor finishes, the parent can read back
    the cached result from the same directory.
    """
    from executorlib import SingleNodeExecutor

    with tempfile.TemporaryDirectory() as tmpdir:
        values_dir = f"{tmpdir}/values"
        calls_dir = f"{tmpdir}/calls"

        # Parent-side cache pointing at the shared directories
        parent_values = ValuePickleFile.with_pickle(root=values_dir)
        parent_calls = CallPickleFile.with_pickle(root=calls_dir)
        parent_cache = Cache(parent_values, parent_calls)

        with SingleNodeExecutor() as executor:
            future = executor.submit(_worker_with_file_cache, 21, values_dir, calls_dir)
            result = future.result()

        assert result == 42, f"Expected 42, got {result}"
        assert parent_cache.contains(double.digest(21)), (
            "With file-backed storage, results written by the worker process are "
            "visible to the parent via the shared filesystem path."
        )


# ---------------------------------------------------------------------------
# BoundWrapper tests
# ---------------------------------------------------------------------------
# BoundWrapper.bind(func) captures the active cache and metadata at bind time
# and restores them on every call, even across process boundaries (provided the
# cache backend is picklable, i.e. file- or SQL-backed).


def test_threadpool_bound_wrapper():
    """
    BoundWrapper propagates the cache to ThreadPoolExecutor workers without
    requiring ctx.run at the call site.
    """
    cache1 = Cache(ValueMemory({}), CallMemory({}))

    with fleche.cache(cache1):
        bound = BoundWrapper.bind(my_func)

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(bound, 300)
        future.result()

    assert cache1.contains(my_func.digest(300)), (
        "BoundWrapper restores the bound cache in the thread so the result is "
        "stored in the parent's cache object."
    )


def test_process_executor_bound_wrapper():
    """
    BoundWrapper with a file-backed cache eliminates the need for a separate
    worker wrapper function: the bound callable carries the cache configuration
    and sets it up automatically in the worker process.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        values_dir = f"{tmpdir}/values"
        calls_dir = f"{tmpdir}/calls"

        file_cache = Cache(
            ValuePickleFile.with_pickle(root=values_dir),
            CallPickleFile.with_pickle(root=calls_dir),
        )

        with fleche.cache(file_cache):
            bound = BoundWrapper.bind(double)

        with concurrent.futures.ProcessPoolExecutor(max_workers=1) as executor:
            result = executor.submit(bound, 21).result()

        assert result == 42, f"Expected 42, got {result}"
        assert file_cache.contains(double.digest(21)), (
            "BoundWrapper carries the file-backed cache into the worker; results "
            "written there are visible to the parent via the shared filesystem path."
        )


@_skip_no_executorlib
def test_executorlib_bound_wrapper():
    """
    BoundWrapper with a file-backed cache works the same way with
    executorlib.SingleNodeExecutor.
    """
    from executorlib import SingleNodeExecutor

    with tempfile.TemporaryDirectory() as tmpdir:
        values_dir = f"{tmpdir}/values"
        calls_dir = f"{tmpdir}/calls"

        file_cache = Cache(
            ValuePickleFile.with_pickle(root=values_dir),
            CallPickleFile.with_pickle(root=calls_dir),
        )

        with fleche.cache(file_cache):
            bound = BoundWrapper.bind(double)

        with SingleNodeExecutor() as executor:
            result = executor.submit(bound, 21).result()

        assert result == 42, f"Expected 42, got {result}"
        assert file_cache.contains(double.digest(21)), (
            "BoundWrapper carries the file-backed cache into the executorlib worker; "
            "results are visible to the parent via the shared filesystem path."
        )
