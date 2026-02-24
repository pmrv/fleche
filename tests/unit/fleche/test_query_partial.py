from fleche import fleche, cache
from fleche.caches import Cache
from fleche.storage import Memory

def test_query_partial_arguments():
    # Setup a fresh memory cache
    test_cache = Cache(values=Memory({}), calls=Memory({}))

    with cache(test_cache):
        @fleche
        def bar(x, y, z=10):
            return x + y + z

        # Test that .call with partial=True works and produces None for missing
        # We need to access the wrapper's get_call which is exposed as .call
        call_obj = bar.call(y=5, partial=True)
        assert call_obj.arguments == {'x': None, 'y': 5, 'z': None}

        # Test that .query uses partial binding
        bar(1, 5, 10)
        bar(2, 5, 20)
        bar(1, 6, 10)

        # Querying for y=5 should return 2 results (x=1, z=10 and x=2, z=20)
        results = list(bar.query(y=5))
        assert len(results) == 2

        # Querying for x=1 should return 2 results (y=5, z=10 and y=6, z=10)
        results = list(bar.query(x=1))
        assert len(results) == 2

def test_query_preserves_order_with_partial():
    @fleche
    def order_func(a, b, c):
        return a

    call_obj = order_func.call(c=3, a=1, partial=True)
    # The order of arguments should follow the function signature
    assert list(call_obj.arguments.keys()) == ['a', 'b', 'c']
    assert call_obj.arguments == {'a': 1, 'b': None, 'c': 3}
