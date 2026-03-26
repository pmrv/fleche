from fleche import fleche, cache


def test_hash_code_integration(cache_fixture):
    # Use a real cache to verify end-to-end behavior
    with cache(cache_fixture):

        def func_v1(x):
            return x + 1

        func_v1.__name__ = "my_func"
        func_v1.__module__ = "my_module"

        wrapped_v1 = fleche(hash_code=True)(func_v1)
        assert wrapped_v1(10) == 11
        assert wrapped_v1.contains(10)

        def func_v2(x):
            return x + 2

        func_v2.__name__ = "my_func"
        func_v2.__module__ = "my_module"

        wrapped_v2 = fleche(hash_code=True)(func_v2)
        # Should NOT be in cache because code changed
        assert not wrapped_v2.contains(10)
        assert wrapped_v2(10) == 12
        assert wrapped_v2.contains(10)


def test_hash_code_disabled_integration(cache_fixture):
    with cache(cache_fixture):

        def func_v1(x):
            return x + 1

        func_v1.__name__ = "my_func"
        func_v1.__module__ = "my_module"

        wrapped_v1 = fleche(hash_code=False)(func_v1)
        assert wrapped_v1(10) == 11
        assert wrapped_v1.contains(10)

        def func_v2(x):
            return x + 2

        func_v2.__name__ = "my_func"
        func_v2.__module__ = "my_module"

        wrapped_v2 = fleche(hash_code=False)(func_v2)
        # Should BE in cache because code change is ignored
        assert wrapped_v2.contains(10)
        assert wrapped_v2(10) == 11  # Returns old value!
