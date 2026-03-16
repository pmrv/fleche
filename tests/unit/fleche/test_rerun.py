from unittest.mock import Mock
from fleche import fleche
from fleche.caches import Cache
from fleche.state import cache
from fleche.storage import Memory

def test_rerun_basic():
    mock_func = Mock(side_effect=[1, 2])

    @fleche
    def func(x):
        return mock_func(x)

    with cache(Cache(Memory({}), Memory({}))):
        # First call: cache miss, execute
        assert func(1) == 1
        assert mock_func.call_count == 1

        # Second call: cache hit
        assert func(1) == 1
        assert mock_func.call_count == 1

        # Rerun: evict and execute
        assert func.rerun(1) == 2
        assert mock_func.call_count == 2

        # Fourth call: cache hit with NEW value
        assert func(1) == 2
        assert mock_func.call_count == 2

def test_rerun_nested():
    mock_inner = Mock(side_effect=[10, 20])
    mock_outer = Mock(side_effect=[100, 200])

    @fleche
    def inner(x):
        return mock_inner(x)

    @fleche
    def outer(x):
        mock_outer(x)
        return inner(x)

    with cache(Cache(Memory({}), Memory({}))):
        # First call: both miss
        assert outer(1) == 10
        assert mock_outer.call_count == 1
        assert mock_inner.call_count == 1

        # Second call: both hit
        assert outer(1) == 10
        assert mock_outer.call_count == 1
        assert mock_inner.call_count == 1

        # Rerun: both should re-execute because of RefreshingCache
        assert outer.rerun(1) == 20
        assert mock_outer.call_count == 2
        assert mock_inner.call_count == 2

        # Verify they are now cached with new values
        assert outer(1) == 20
        assert mock_outer.call_count == 2
        assert mock_inner.call_count == 2

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

    with cache(Cache(Memory({}), Memory({}))):
        assert l1(0) == 1
        assert mock_l3.call_count == 1

        assert l1(0) == 1
        assert mock_l3.call_count == 1

        # rerun l1 should rerun everything down the line
        assert l1.rerun(0) == 2
        assert mock_l3.call_count == 2

        # rerun l2 should rerun l3, but l1 will still be hit if called normally
        assert l2.rerun(0) == 3
        assert mock_l3.call_count == 3

        assert l1(0) == 2 # l1 still has the value from its last run
