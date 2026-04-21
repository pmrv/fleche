"""
Tests for calling fleche-decorated functions through a ProcessPoolExecutor.

Issue: https://github.com/pmrv/fleche/issues/172
"""
from concurrent.futures import ProcessPoolExecutor


from fleche import fleche, cache
from fleche.caches import Cache
from fleche.storage import ValueMemory, CallMemory


# Module-level decorated function — must be at module level to be picklable
@fleche
def _add(x, y):
    return x + y


@fleche
def _square(x):
    return x * x


def _call_add_with_memory_cache(args):
    """Worker that runs _add inside a fresh Memory cache."""
    x, y = args
    with cache(Cache(ValueMemory({}), CallMemory({}))):
        return _add(x, y)


def _call_square_with_memory_cache(x):
    """Worker that runs _square inside a fresh Memory cache."""
    with cache(Cache(ValueMemory({}), CallMemory({}))):
        return _square(x)


def _get_digest(args):
    """Worker that calls the .digest helper attribute."""
    x, y = args
    return _add.fleche.digest(x, y)


def _call_add_no_cache_setup(args):
    """Worker that calls _add without setting up a cache (uses default from config)."""
    x, y = args
    return _add(x, y)


class TestProcessPool:
    """Integration tests: call fleche-wrapped functions through ProcessPoolExecutor."""

    def test_submit_with_memory_cache(self):
        with ProcessPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(_call_add_with_memory_cache, (i, i + 1)) for i in range(4)]
            results = [f.result() for f in futures]
        assert results == [1, 3, 5, 7]

    def test_map_with_memory_cache(self):
        args = [(i, i + 1) for i in range(4)]
        with ProcessPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(_call_add_with_memory_cache, args))
        assert results == [1, 3, 5, 7]

    def test_map_square_with_memory_cache(self):
        with ProcessPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(_call_square_with_memory_cache, range(5)))
        assert results == [0, 1, 4, 9, 16]

    def test_digest_helper_in_worker(self):
        """The .digest helper should work in worker processes (no cache needed)."""
        args = [(1, 2), (3, 4)]
        with ProcessPoolExecutor(max_workers=2) as executor:
            digests = list(executor.map(_get_digest, args))
        # Verify digests are non-empty strings
        assert all(isinstance(d, str) and len(d) > 0 for d in digests)
        # Same inputs should yield the same digest in worker as in main process
        assert digests[0] == _add.fleche.digest(1, 2)
        assert digests[1] == _add.fleche.digest(3, 4)

    def test_result_consistency_across_processes(self):
        """Results computed in workers should match direct calls."""
        args = [(i, i * 2) for i in range(6)]
        expected = [_add.__wrapped__(x, y) for x, y in args]

        with ProcessPoolExecutor(max_workers=3) as executor:
            results = list(executor.map(_call_add_with_memory_cache, args))

        assert results == expected
