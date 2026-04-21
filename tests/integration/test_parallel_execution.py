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


# ---------------------------------------------------------------------------
# wrap_executor tests
# ---------------------------------------------------------------------------
# ``fleche.wrap_executor`` monkey-patches ``executor.submit`` so that
# fleche-wrapped functions are bound at submission time, and cache hits short-
# circuit the executor entirely.


@fleche.fleche
def triple(x):
    return x * 3


def _plain_add(a, b):
    return a + b


class _NeverSubmitExecutor:
    """Executor stub that explodes if ``submit`` is actually called.

    Used to prove that a cache-hit path never reaches the underlying executor.
    """

    def submit(self, func, *args, **kwargs):
        raise AssertionError(
            f"submit should not have been called (func={func!r}, "
            f"args={args}, kwargs={kwargs})"
        )


class _RecordingExecutor:
    """Executor stub whose ``submit`` declares a keyword-only ``resource_dict``.

    Captures what was forwarded to ``submit`` and what the callable was
    invoked with, so tests can assert the kwarg split.
    """

    def __init__(self):
        self.submit_args = None
        self.submit_kwargs = None
        self.call_args = None
        self.call_kwargs = None
        self.result = None

    def submit(self, func, *args, resource_dict=None, **kwargs):
        self.submit_args = args
        self.submit_kwargs = {"resource_dict": resource_dict, **kwargs}

        def _run(*a, **kw):
            self.call_args = a
            self.call_kwargs = kw
            self.result = func(*a, **kw)
            return self.result

        fut = concurrent.futures.Future()
        fut.set_result(_run(*args, **kwargs))
        return fut


def test_wrap_executor_passthrough_non_fleche():
    """Non-fleche callables go straight to the original submit."""
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        fleche.wrap_executor(executor)
        result = executor.submit(_plain_add, 2, 3).result()

    assert result == 5


def test_wrap_executor_thread_cache_miss():
    """A cache miss on a wrapped ThreadPoolExecutor binds state and submits."""
    cache1 = Cache(ValueMemory({}), CallMemory({}))

    with fleche.cache(cache1):
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            fleche.wrap_executor(executor)
            future = executor.submit(my_func, 400)
            assert future.result() == 401

    assert cache1.contains(my_func.digest(400)), (
        "wrap_executor should bind the current cache into the worker so the "
        "result is stored in the parent's cache object."
    )


def test_wrap_executor_cache_hit_skips_submit():
    """A cache hit returns a completed Future without ever calling submit."""
    cache1 = Cache(ValueMemory({}), CallMemory({}))

    with fleche.cache(cache1):
        # seed the cache
        assert triple(7) == 21

        executor = _NeverSubmitExecutor()
        fleche.wrap_executor(executor)

        future = executor.submit(triple, 7)

    assert future.done()
    assert future.result() == 21


def test_process_executor_wrap_executor(file_cache):
    """wrap_executor replaces manual BoundWrapper.bind for a ProcessPoolExecutor.

    Analogue of test_process_executor_bound_wrapper: the user submits the
    fleche function directly, and the patched submit takes care of binding.
    """
    with fleche.cache(file_cache):
        with concurrent.futures.ProcessPoolExecutor(max_workers=1) as executor:
            fleche.wrap_executor(executor)
            result = executor.submit(double, 21).result()

    assert result == 42, f"Expected 42, got {result}"
    assert file_cache.contains(double.digest(21)), (
        "wrap_executor binds the file-backed cache into the worker; "
        "results are visible to the parent via the shared filesystem path."
    )


def test_wrap_executor_splits_submit_kwargs():
    """Keyword-only params on submit are forwarded to submit, not the callable."""
    cache1 = Cache(ValueMemory({}), CallMemory({}))
    executor = _RecordingExecutor()

    with fleche.cache(cache1):
        fleche.wrap_executor(executor)
        future = executor.submit(my_func, resource_dict={"cores": 4}, x=42)

    assert future.result() == 43
    assert executor.submit_kwargs == {"resource_dict": {"cores": 4}}
    # The bound wrapper is invoked with *no* args/kwargs from the recording
    # stub; the function payload (x=42) was baked into the BoundWrapper via
    # ``func.fleche.bind``.
    assert executor.call_args == ()
    assert executor.call_kwargs == {}
    assert cache1.contains(my_func.digest(42))


def test_wrap_executor_is_idempotent():
    """Wrapping the same executor twice installs a single interception layer."""
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        fleche.wrap_executor(executor)
        patched_once = executor.submit
        fleche.wrap_executor(executor)
        # The second call must not replace or stack on the first patch.
        assert executor.submit is patched_once


@_skip_no_executorlib
def test_executorlib_wrap_executor(file_cache):
    """wrap_executor works with executorlib.SingleNodeExecutor."""
    from executorlib import SingleNodeExecutor

    with fleche.cache(file_cache):
        with SingleNodeExecutor() as executor:
            fleche.wrap_executor(executor)
            result = executor.submit(double, 21).result()

    assert result == 42, f"Expected 42, got {result}"
    assert file_cache.contains(double.digest(21))
