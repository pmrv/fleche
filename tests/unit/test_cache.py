from unittest.mock import Mock
import pytest
from fleche import fleche, cache, Cache
from fleche.digest import digest
from fleche.cache import ReadOnlyCache, CacheStack, Rejected


def test_cache_save():
    from fleche.invocation import Invocation
    values_storage = Mock()
    invocs_storage = Mock()
    metadata = Mock()
    c = Cache(values_storage, invocs_storage).metadb(metadata)
    
    inv = Invocation(name="test", args=(1,), kwargs={}, result="result")
    inv.metadata = {"test": {"key": "value"}}
    c.save(inv)
    
    # Check that the underlying cache saves values and invocations
    assert values_storage.save.called
    assert invocs_storage.save.called
    # Check that metadata is saved
    assert metadata.save.called


def test_cache_load():
    values_storage = Mock()
    invocs_storage = Mock()
    metadata = Mock()
    c = Cache(values_storage, invocs_storage).metadb(metadata)
    c.load("key")
    invocs_storage.load.assert_called_once_with("key")
    metadata.load.assert_not_called()


def test_cache_context_manager():
    @fleche
    def my_func(x):
        return x * 2

    # a mock cache to be the original one
    original_values = Mock()
    original_values.save.return_value = "digest_value"
    original_invocs = Mock()
    original_invocs.load.side_effect = KeyError
    original_cache = Cache(original_values, original_invocs)

    # a mock cache to be the new one
    new_values = Mock()
    new_values.save.return_value = "digest_value"
    new_invocs = Mock()
    new_invocs.load.side_effect = KeyError
    new_cache = Cache(new_values, new_invocs)

    # get the default cache and replace it with our mock original_cache
    default_cache = cache()
    with cache(original_cache):

        with cache(new_cache):
            assert cache() is new_cache
            my_func(2)
            new_cache.invocs.load.assert_called_once()
            assert new_cache.invocs.save.call_count == 1

        assert cache() is original_cache
        my_func(3)
        original_cache.invocs.load.assert_called_once()
        assert original_cache.invocs.save.call_count == 1

    # ensure the default cache is restored
    assert cache() is default_cache


@pytest.mark.xfail
def test_base_cache_transfer():
    values_storage = Mock()
    invocs_storage = Mock()
    invocs_storage.list.return_value = ["key1", "key2"]
    invocs_storage.load.side_effect = ["result1", "result2"]
    metadata = Mock()
    metadata.load.side_effect = ["metadata1", "metadata2"]

    c1 = Cache(values_storage, invocs_storage).metadb(metadata)

    other_values_storage = Mock()
    other_invocs_storage = Mock()
    other_metadata = Mock()
    c2 = Cache(other_values_storage, other_invocs_storage).metadb(other_metadata)

    c1.transfer(c2)

    assert other_invocs_storage.save.call_count == 2
    other_invocs_storage.save.assert_any_call("key1", "result1")
    other_invocs_storage.save.assert_any_call("key2", "result2")

    assert other_metadata.save.call_count == 2
    other_metadata.save.assert_any_call("key1", "metadata1")
    other_metadata.save.assert_any_call("key2", "metadata2")


def test_readonly_cache_save():
    from fleche.invocation import Invocation
    c = ReadOnlyCache(Mock())
    inv = Invocation(name="test", args=(1,), kwargs={}, result="result")
    with pytest.raises(Rejected):
        c.save(inv)


def test_readonly_cache_load():
    mock_cache = Mock()
    c = ReadOnlyCache(mock_cache)
    c.load("key")
    mock_cache.load.assert_called_once_with("key")


def test_cache_stack_save():
    from fleche.invocation import Invocation
    c1 = Mock()
    c2 = Mock()
    stack = CacheStack((c1, c2))
    inv = Invocation(name="test", args=(1,), kwargs={}, result="result")
    stack.save(inv)
    c1.save.assert_called_once()
    c2.save.assert_not_called()


def test_cache_stack_load_hit():
    from fleche.invocation import Invocation
    c1 = Mock()
    c1.load.side_effect = KeyError
    c2 = Mock()
    inv = Invocation(name="test", args=(1,), kwargs={}, result="result")
    c2.load.return_value = inv
    stack = CacheStack((c1, c2))
    result = stack.load("key")
    c1.load.assert_called_once_with("key")
    c2.load.assert_called_once_with("key")
    assert result == inv


def test_cache_stack_load_miss():
    c1 = Mock()
    c1.load.side_effect = KeyError
    c2 = Mock()
    c2.load.side_effect = KeyError
    stack = CacheStack((c1, c2))
    with pytest.raises(KeyError):
        stack.load("key")
