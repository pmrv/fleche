
from unittest.mock import Mock
from fleche import fleche, cache, Cache

def test_cache_context_manager():
    @fleche
    def my_func(x):
        return x * 2

    # a mock cache to be the original one
    original_cache = Cache(Mock(), Mock())
    original_cache.storage.load.side_effect = KeyError

    # a mock cache to be the new one
    new_cache = Cache(Mock(), Mock())
    new_cache.storage.load.side_effect = KeyError

    # get the default cache and replace it with our mock original_cache
    default_cache = cache()
    with cache(original_cache):

        with cache(new_cache):
            assert cache() is new_cache
            my_func(2)
            new_cache.storage.load.assert_called_once()
            new_cache.metadata.save.assert_called_once()
            new_cache.storage.save.assert_called_once()

        assert cache() is original_cache
        my_func(3)
        original_cache.storage.load.assert_called_once()
        original_cache.metadata.save.assert_called_once()
        original_cache.storage.save.assert_called_once()

    # ensure the default cache is restored
    assert cache() is default_cache
