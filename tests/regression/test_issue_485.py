"""
Regression test for issue #485: narrow _in_flight to cover only the cache-write gap.

CPython's Future.set_result() releases the condition lock before calling
_invoke_callbacks().  This means a thread blocked on future.result() can be
unblocked while the done-callback that saves to the cache has not yet run.

The fix: _in_flight[key] is populated at the START of _cache() (before
cache.save) and removed in its finally clause.  A concurrent compute() call
that arrives during that window finds the future in _in_flight, calls
.result() (which returns immediately — the future is already resolved), and
returns the value without triggering a second function invocation.
"""
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from unittest.mock import patch

from fleche import fleche
from fleche.caches import Cache
from fleche.state import cache
from fleche.storage import ValueMemory, CallMemory


def _make_cache():
    return Cache(ValueMemory({}), CallMemory({}))


def _wait_for_cache(fn, *args, timeout=2.0):
    deadline = time.monotonic() + timeout
    while not fn.contains(*args):
        assert time.monotonic() < deadline, f"cache never populated for args {args}"
        time.sleep(0.001)


def test_in_flight_covers_cache_write_gap():
    """
    _in_flight[key] is set before cache.save so a second compute() call that
    arrives while the save is in progress gets the value without re-executing
    the function.

    Threading.Barrier is used to hold the done-callback at the start of
    cache.save.  While it is paused, a second compute() call is made; it
    should find the key in _in_flight and return without incrementing
    call_count.  Both calls use the same key, so the cache count alone can't
    distinguish the fix from the bug; instead we assert on call metadata --
    the function is invoked exactly once (call_count) and cache.save runs
    exactly once (save_count).
    """
    barrier = threading.Barrier(2)
    save_started = threading.Event()
    save_count = [0]
    call_count = [0]
    ready = threading.Event()

    real_save = Cache.save

    def slow_save(self_cache, call):
        save_started.set()
        barrier.wait()
        save_count[0] += 1
        return real_save(self_cache, call)

    executor = ThreadPoolExecutor(max_workers=1)

    try:
        with patch.object(Cache, "save", slow_save):
            c = _make_cache()

            @fleche
            def compute(x):
                call_count[0] += 1
                def work():
                    # Hold the worker until the main thread has registered the
                    # done-callback, ensuring the callback runs in the worker
                    # thread (not synchronously in the calling thread).
                    ready.wait()
                    return x * 2
                return executor.submit(work)

            with cache(c):
                future = compute(5)

                # Allow the worker to resolve the future; the done-callback
                # (_cache) is already registered and will run in the worker
                # thread via _invoke_callbacks().
                ready.set()

                assert future.result() == 10
                assert call_count[0] == 1

                # Wait until the callback has entered slow_save (meaning
                # _in_flight[key] is now set but cache.save has not yet run).
                assert save_started.wait(timeout=2.0), "callback never reached slow_save"

                # A second compute(5) during the save window should find the
                # key in _in_flight and return the value without calling func.
                second = compute(5)
                assert second == 10
                assert call_count[0] == 1, "_in_flight check did not prevent second invocation"

                # Release the callback to complete the save.
                barrier.wait()

                _wait_for_cache(compute, 5)
                assert save_count[0] == 1, f"cache.save called {save_count[0]} times, expected 1"

                # Third call: plain cache hit.
                third = compute(5)
                assert third == 10
                assert call_count[0] == 1
    finally:
        executor.shutdown(wait=True)
