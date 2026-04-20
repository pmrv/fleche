"""
Tests for fleche's Future pass-through feature.

When a fleche-decorated function returns a concurrent.futures.Future,
fleche passes the future back to the caller and attaches a done callback
that caches the result once the future completes.
"""
from concurrent.futures import Future, ThreadPoolExecutor, ProcessPoolExecutor
from unittest.mock import Mock

from fleche import fleche
from fleche.caches import Cache
from fleche.state import cache
from fleche.storage import ValueMemory, CallMemory


def _make_cache():
    return Cache(ValueMemory({}), CallMemory({}))


class TestThreadPoolFutures:
    """fleche wraps functions that return Futures from a ThreadPoolExecutor."""

    def test_returns_future(self):
        """The decorated function should return the Future, not the unwrapped value."""
        executor = ThreadPoolExecutor(max_workers=1)
        try:
            @fleche
            def compute(x):
                return executor.submit(lambda: x * 2)

            with cache(_make_cache()):
                result = compute(5)
                assert isinstance(result, Future)
                assert result.result() == 10
        finally:
            executor.shutdown(wait=False)

    def test_result_is_cached_after_future_completes(self):
        """After the future resolves, the result should be cached for subsequent calls."""
        call_count = 0
        executor = ThreadPoolExecutor(max_workers=1)
        try:
            @fleche
            def compute(x):
                nonlocal call_count
                call_count += 1
                return executor.submit(lambda: x * 2)

            with cache(_make_cache()):
                future = compute(5)
                assert future.result() == 10
                # Done callback has run — result is now cached
                assert call_count == 1

                second = compute(5)
                # Cache hit: returns the plain value, not a future
                assert second == 10
                assert call_count == 1
        finally:
            executor.shutdown(wait=False)

    def test_different_args_are_cached_independently(self):
        """Each distinct argument set should get its own cache entry."""
        executor = ThreadPoolExecutor(max_workers=2)
        try:
            @fleche
            def compute(x):
                return executor.submit(lambda: x * 3)

            with cache(_make_cache()):
                f1 = compute(4)
                f2 = compute(7)
                assert f1.result() == 12
                assert f2.result() == 21

                assert compute(4) == 12
                assert compute(7) == 21
        finally:
            executor.shutdown(wait=False)

    def test_none_result_is_not_cached(self):
        """A Future resolving to None should not be cached (matches non-future behavior)."""
        call_count = 0
        executor = ThreadPoolExecutor(max_workers=1)
        try:
            @fleche
            def compute(x):
                nonlocal call_count
                call_count += 1
                return executor.submit(lambda: None)

            with cache(_make_cache()):
                future = compute(1)
                assert future.result() is None
                assert call_count == 1

                # Result was not cached; function is called again
                second = compute(1)
                if isinstance(second, Future):
                    assert second.result() is None
                else:
                    assert second is None
                assert call_count == 2
        finally:
            executor.shutdown(wait=False)

    def test_multiple_futures_concurrent(self):
        """Multiple concurrent futures should all be cached independently."""
        executor = ThreadPoolExecutor(max_workers=4)
        try:
            @fleche
            def compute(x):
                return executor.submit(lambda: x ** 2)

            with cache(_make_cache()):
                futures = [compute(i) for i in range(5)]
                results = [f.result() for f in futures]
                assert results == [0, 1, 4, 9, 16]

                # All results should now be cached
                cached = [compute(i) for i in range(5)]
                assert cached == [0, 1, 4, 9, 16]
        finally:
            executor.shutdown(wait=False)

    def test_non_future_function_unaffected(self):
        """Regular (non-Future-returning) functions should behave exactly as before."""
        call_count = 0

        @fleche
        def compute(x):
            nonlocal call_count
            call_count += 1
            return x * 2

        with cache(_make_cache()):
            assert compute(5) == 10
            assert compute(5) == 10
            assert call_count == 1


# Module-level decorated function for ProcessPoolExecutor (must be picklable)
@fleche
def _pp_compute(x):
    return x * 4


def _submit_pp_compute(x):
    with cache(_make_cache()):
        return _pp_compute(x)


class TestProcessPoolFutures:
    """fleche-decorated functions called from a ProcessPoolExecutor."""

    def test_processpool_submit_and_cache(self):
        """Results computed in worker processes are cached and returned correctly."""
        with ProcessPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(_submit_pp_compute, i) for i in range(4)]
            results = [f.result() for f in futures]
        assert results == [0, 4, 8, 12]

    def test_processpool_result_consistency(self):
        """Values computed via ProcessPoolExecutor match direct calls."""
        inputs = list(range(5))
        expected = [_pp_compute.__wrapped__(x) for x in inputs]

        with ProcessPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(_submit_pp_compute, inputs))

        assert results == expected
