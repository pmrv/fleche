
from unittest.mock import Mock, MagicMock

from fleche import fleche, Cache, _CACHE, cache
from fleche.digest import digest
from fleche.invocation import Invocation
from fleche.storage import Memory


def setup_function():
    values_storage = Mock()
    values_storage.save.return_value = "digest_value"
    invocs_storage = Mock()
    invocs_storage.load.side_effect = KeyError
    c = Cache(values_storage, invocs_storage)
    _CACHE.set(c)


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
    mock_meta = MagicMock()
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

    key = digest(Invocation.from_call(my_func, 2).to_lookup())

    with cache(Cache(Memory({}), Memory({}))):
        # First call, should execute the function and save to cache
        assert my_func(2) == 42
        mock_function.assert_called_once_with(2)
        assert cache().contains(key)

        # Second call, should load from cache
        assert my_func(2) == 42
        mock_function.assert_called_once_with(2)


def test_fleche_with_version_argument():
    mock_function = Mock(return_value=42)
    mock_function.__name__ = 'mock_function'

    @fleche(version=1)
    def my_func(x):
        return mock_function(x)

    cache = Cache(Mock(), Mock())
    storage_content = {}

    def load_from_storage(k):
        if k not in storage_content:
            raise KeyError(k)
        return storage_content[k]

    def save_to_storage(v, key=None):
        k = digest(v.to_lookup())
        storage_content[k] = v
        return k

    cache.invocs.load = Mock(side_effect=load_from_storage)
    cache.invocs.save = Mock(side_effect=save_to_storage)
    cache.values.save = Mock(return_value="digest_value")

    # First call, should execute the function and save to cache
    assert my_func(2) == 42
    mock_function.assert_called_once_with(2)

    # Second call, with different version, should execute again
    @fleche(version=2)
    def my_func_v2(x):
        return mock_function(x)

    assert my_func_v2(2) == 42
    assert mock_function.call_count == 2


def test_fleche_with_version():
    mock_function = Mock(return_value=42)
    mock_function.__name__ = 'mock_function'

    with cache(Cache(Memory({}), Memory({}))):
        mock_function.__version__ = 1
        my_func = fleche(mock_function)

        # First call, should execute the function and save to cache
        assert my_func(2) == 42
        mock_function.assert_called_once_with(2)
        inv = Invocation.from_call(my_func, 2)
        inv.version = 1
        key_v1 = digest(inv.to_lookup())
        assert cache().contains(key_v1)

        mock_function.__version__ = 2
        my_func = fleche(mock_function)

        # Second call, with different version, should execute again
        assert my_func(2) == 42
        assert mock_function.call_count == 2
        inv.version = 2
        key_v2 = digest(inv.to_lookup())
        assert cache().contains(key_v2)


def test_fleche_with_module():
    mock_function = Mock(return_value=42)
    mock_function.__name__ = "name"

    with cache(Cache(Memory({}), Memory({}))):
        # First call, should execute the function and save to cache
        mock_function.__module__ = "module1"
        # need to assigne dunder before wrapping for fleche to pick it up
        my_func = fleche(mock_function)

        assert my_func(2) == 42
        mock_function.assert_called_once_with(2)
        inv = Invocation.from_call(my_func, 2)
        inv.module = "module1"
        key_m1 = digest(inv.to_lookup())
        assert cache().contains(key_m1)

        # Second call, with different module, should execute again
        mock_function.__module__ = "module2"
        my_func = fleche(mock_function)
        assert my_func(2) == 42
        assert mock_function.call_count == 2
        inv.module = "module2"
        key_m2 = digest(inv.to_lookup())
        assert cache().contains(key_m2)
