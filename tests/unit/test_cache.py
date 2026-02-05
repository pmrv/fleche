
from unittest.mock import Mock
import pytest
from fleche import fleche, cache, Cache
from fleche.cache import ReadOnlyCache, CacheStack, SaveError


def test_cache_save():
    storage = Mock()
    metadata = Mock()
    c = Cache(metadata, storage)
    c.save("key", "result", "metadata")
    storage.save.assert_called_once_with("key", "result")
    metadata.save.assert_called_once_with("key", "metadata")


def test_cache_load():
    storage = Mock()
    metadata = Mock()
    c = Cache(metadata, storage)
    c.load("key")
    storage.load.assert_called_once_with("key")
    metadata.load.assert_called_once_with("key")


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


def test_base_cache_transfer():
    storage = Mock()
    storage.list.return_value = ["key1", "key2"]
    storage.load.side_effect = ["result1", "result2"]
    metadata = Mock()
    metadata.load.side_effect = ["metadata1", "metadata2"]

    c1 = Cache(metadata, storage)

    other_storage = Mock()
    other_metadata = Mock()
    c2 = Cache(other_metadata, other_storage)

    c1.transfer(c2)

    assert other_storage.save.call_count == 2
    other_storage.save.assert_any_call("key1", "result1")
    other_storage.save.assert_any_call("key2", "result2")

    assert other_metadata.save.call_count == 2
    other_metadata.save.assert_any_call("key1", "metadata1")
    other_metadata.save.assert_any_call("key2", "metadata2")


def test_readonly_cache_save():
    c = ReadOnlyCache(Mock())
    with pytest.raises(SaveError):
        c.save("key", "result", "metadata")


def test_readonly_cache_load():
    mock_cache = Mock()
    c = ReadOnlyCache(mock_cache)
    c.load("key")
    mock_cache.load.assert_called_once_with("key")


def test_cache_stack_save():
    c1 = Mock()
    c2 = Mock()
    stack = CacheStack((c1, c2))
    stack.save("key", "result", "metadata")
    c1.save.assert_called_once_with("key", "result", "metadata")
    c2.save.assert_not_called()


def test_cache_stack_load_hit():
    c1 = Mock()
    c1.load.side_effect = KeyError
    c2 = Mock()
    c2.load.return_value = ("result", "metadata")
    stack = CacheStack((c1, c2))
    result, metadata = stack.load("key")
    c1.load.assert_called_once_with("key")
    c2.load.assert_called_once_with("key")
    assert result == "result"
    assert metadata == "metadata"


def test_cache_stack_load_miss():
    c1 = Mock()
    c1.load.side_effect = KeyError
    c2 = Mock()
    c2.load.side_effect = KeyError
    stack = CacheStack((c1, c2))
    with pytest.raises(KeyError):
        stack.load("key")
