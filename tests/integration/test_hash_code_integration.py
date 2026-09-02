from fleche import fleche, cache
from fleche.caches import Cache
from fleche.storage import ValueMemory, CallMemory


def test_hash_code_integration():
    # Use a real cache to verify end-to-end behavior
    with cache(Cache(ValueMemory({}), CallMemory({}))):

        def func_v1(x):
            return x + 1

        func_v1.__name__ = "my_func"
        func_v1.__qualname__ = "my_func"
        func_v1.__module__ = "my_module"

        wrapped_v1 = fleche(hash_code=True)(func_v1)
        assert wrapped_v1(10) == 11
        assert wrapped_v1.fleche.contains(10)

        def func_v2(x):
            return x + 2

        func_v2.__name__ = "my_func"
        func_v2.__qualname__ = "my_func"
        func_v2.__module__ = "my_module"

        wrapped_v2 = fleche(hash_code=True)(func_v2)
        # Should NOT be in cache because code changed
        assert not wrapped_v2.fleche.contains(10)
        assert wrapped_v2(10) == 12
        assert wrapped_v2.fleche.contains(10)


def test_hash_code_closures_do_not_share_a_cache_entry():
    """Two closures out of one factory must not serve each other's results.

    They agree on qualname, module and code object, so before captured
    variables were digested ``make(3)(5)`` returned ``make(2)``'s cached 10.
    """
    with cache(Cache(ValueMemory({}), CallMemory({}))):

        def make(n):
            def scale(x):
                return x * n
            return scale

        double = fleche(hash_code=True)(make(2))
        triple = fleche(hash_code=True)(make(3))

        assert double(5) == 10
        assert double.fleche.contains(5)
        # the entry double just wrote must not answer for triple
        assert not triple.fleche.contains(5)
        assert triple(5) == 15
