
from unittest.mock import Mock
from fleche import fleche, Cache, _CACHE

from fleche.invocation import Invocation


def setup_function():
    cache = Cache(Mock(), Mock())
    cache.storage.load.side_effect = KeyError
    _CACHE.set(cache)


def test_fleche_no_args():
    @fleche
    def my_func(x):
        return x * 2

    assert my_func(2) == 4


def test_fleche_with_args():
    @fleche()
    def my_func(x):
        return x * 2

    assert my_func(3) == 6


def test_fleche_with_meta():
    mock_meta = Mock()
    mock_meta.name = "my_meta"

    @fleche(meta=(mock_meta,))
    def my_func(x):
        return x * 2

    assert my_func(4) == 8
    mock_meta.pre.assert_called_once_with(
            Invocation(name='my_func', args=(4,), kwargs={}, module='test_fleche', version=None)
    )
    mock_meta.post.assert_called_once()


def test_fleche_retrieves_from_cache():
    mock_function = Mock(return_value=42)
    mock_function.__name__ = 'mock_function'

    @fleche
    def my_func(x):
        return mock_function(x)

    cache = _CACHE.get()
    cache.storage.load.side_effect = [KeyError, 42]

    # First call, should execute the function and save to cache
    assert my_func(2) == 42
    mock_function.assert_called_once_with(2)
    cache.storage.save.assert_called_once()

    # Second call, should load from cache
    assert my_func(2) == 42
    mock_function.assert_called_once_with(2) # Not called again
    cache.storage.load.assert_called()
    assert cache.storage.load.call_count == 2
