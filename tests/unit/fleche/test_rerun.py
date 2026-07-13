from unittest.mock import Mock
from fleche import fleche
from fleche.caches import Cache
from fleche.state import cache
from fleche.storage import ValueMemory, CallMemory

def test_rerun_basic():
    mock_func = Mock(side_effect=[1, 2])

    @fleche
    def func(x):
        return mock_func(x)

    with cache(Cache(ValueMemory({}), CallMemory({}))):
        # First call: cache miss, execute
        assert func(1) == 1
        assert mock_func.call_count == 1

        # Second call: cache hit
        assert func(1) == 1
        assert mock_func.call_count == 1

        # Rerun: re-execute and overwrite
        assert func.fleche.rerun(1) == 2
        assert mock_func.call_count == 2

        # Fourth call: cache hit with NEW value
        assert func(1) == 2
        assert mock_func.call_count == 2

def test_rerun_none_evicts_stale_entry():
    mock_func = Mock(side_effect=[1, None, 2])

    @fleche
    def func(x):
        return mock_func(x)

    with cache(Cache(ValueMemory({}), CallMemory({}))):
        # First call: cache miss, execute and cache 1
        assert func(1) == 1
        assert mock_func.call_count == 1

        # Cache hit, still 1
        assert func(1) == 1
        assert mock_func.call_count == 1

        # Rerun returns None: not cached, and the stale entry for 1 is evicted
        assert func.fleche.rerun(1) is None
        assert mock_func.call_count == 2

        # Since the prior entry was evicted, this is a cache miss again
        assert func(1) == 2
        assert mock_func.call_count == 3


def test_rerun_nested_multiple_levels():
    mock_l3 = Mock(side_effect=[1, 2, 3])

    @fleche
    def l3(x):
        return mock_l3(x)

    @fleche
    def l2(x):
        return l3(x)

    @fleche
    def l1(x):
        return l2(x)

    with cache(Cache(ValueMemory({}), CallMemory({}))):
        assert l1(0) == 1
        assert mock_l3.call_count == 1

        assert l1(0) == 1
        assert mock_l3.call_count == 1

        # rerun l1 should rerun everything down the line
        assert l1.fleche.rerun(0) == 2
        assert mock_l3.call_count == 2

        # rerun l2 should rerun l3, but l1 will still be hit if called normally
        assert l2.fleche.rerun(0) == 3
        assert mock_l3.call_count == 3

        assert l1(0) == 2 # l1 still has the value from its last run
