from pytest import fixture

from fleche import fleche, cache
from fleche.call import QueryCall
from fleche.caches import Cache
from fleche.storage import Memory


@fixture
def test_cache():
    return Cache(values=Memory({}), _calls=Memory({}))


def test_query_partial_arguments(test_cache):
    with cache(test_cache):

        @fleche
        def bar(x, y, z=10):
            return x + y + z

        call_obj = QueryCall.from_call(bar, y=5)
        assert call_obj.arguments == {"x": None, "y": 5, "z": 10}

        # Test that .query uses partial binding
        bar(1, 5, 10)
        bar(2, 5, 20)
        bar(1, 6, 10)

        # Querying for y=5 with z=None explicitly restores wildcard behavior
        # Should return 2 results (x=1, y=5, z=10 and x=2, y=5, z=20)
        results = list(bar.query(y=5, z=None))
        assert len(results) == 2

        # Querying for x=1 with z=None explicitly restores wildcard behavior
        # Should return 2 results (x=1, y=5, z=10 and x=1, y=6, z=10)
        results = list(bar.query(x=1, z=None))
        assert len(results) == 2

        # Querying for y=5 should return 1 results (x=1, z=10), since default z=10 is applied
        results = list(bar.query(y=5))
        assert len(results) == 1

        # Querying for x=1 should return 2 results (y=5, z=10 and y=6, z=10)
        results = list(bar.query(x=1))
        assert len(results) == 2


def test_query_preserves_order_with_partial():
    @fleche
    def order_func(a, b, c):
        return a

    call_obj = QueryCall.from_call(order_func, c=3, a=1)
    # The order of arguments should follow the function signature
    assert list(call_obj.arguments.keys()) == ["a", "b", "c"]
    assert call_obj.arguments == {"a": 1, "b": None, "c": 3}
