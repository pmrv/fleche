from unittest.mock import Mock, MagicMock

from fleche import fleche
from fleche.caches import Cache
from fleche.state import _CACHE, cache
from fleche.storage import ValueMemory, CallMemory


def setup_function():
    values_storage = Mock()
    values_storage.save.return_value = "digest_value"
    calls_storage = Mock()
    calls_storage.load.side_effect = KeyError
    c = Cache(values_storage, calls_storage)
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
    mock_meta.pre.assert_called_once()
    mock_meta.post.assert_called_once()


def test_fleche_retrieves_from_cache():
    mock_function = Mock(return_value=42)
    mock_function.__name__ = "mock_function"

    @fleche
    def my_func(x):
        return mock_function(x)

    key = my_func.fleche.digest(2)

    with cache(Cache(ValueMemory({}), CallMemory({}))):
        # First call, should execute the function and save to cache
        assert my_func(2) == 42
        mock_function.assert_called_once_with(2)
        assert cache().contains(key)

        # Second call, should load from cache
        assert my_func(2) == 42
        mock_function.assert_called_once_with(2)


def test_fleche_with_version_argument():
    mock_function = Mock(return_value=42)
    mock_function.__name__ = "mock_function"

    @fleche(version=1)
    def my_func(x):
        return mock_function(x)

    c = Cache(ValueMemory({}), CallMemory({}))

    with cache(c):
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
    mock_function.__name__ = "mock_function"

    with cache(Cache(ValueMemory({}), CallMemory({}))):
        mock_function.__version__ = 1
        my_func = fleche(mock_function)

        # First call, should execute the function and save to cache
        assert my_func(2) == 42
        mock_function.assert_called_once_with(2)
        key_v1 = my_func.fleche.digest(2)
        assert cache().contains(key_v1)

        mock_function.__version__ = 2
        my_func = fleche(mock_function)

        # Second call, with different version, should execute again
        assert my_func(2) == 42
        assert mock_function.call_count == 2
        key_v2 = my_func.fleche.digest(2)
        assert cache().contains(key_v2)


def test_fleche_with_module():
    # Two independent callables, each with its own module — exercises the
    # "different module → different cache key" path.  We don't reuse one
    # Mock and mutate its __module__ because per-function statics
    # (signature, code digest, version info) are cached on func identity.
    def make_mock(module):
        m = Mock(return_value=42)
        m.__name__ = "name"
        m.__qualname__ = "name"
        m.__module__ = module
        return m

    with cache(Cache(ValueMemory({}), CallMemory({}))):
        m1 = make_mock("json")
        my_func = fleche(m1)
        assert my_func(2) == 42
        m1.assert_called_once_with(2)
        key_m1 = my_func.fleche.digest(2)
        assert cache().contains(key_m1)

        m2 = make_mock("os")
        my_func = fleche(m2)
        assert my_func(2) == 42
        m2.assert_called_once_with(2)
        key_m2 = my_func.fleche.digest(2)
        assert cache().contains(key_m2)
        assert key_m1 != key_m2


def test_fleche_with_unhashable_callable():
    # Callable instance with __hash__ = None.  Per-function caches in
    # call.py would raise TypeError on lookup; the wrapper must fall
    # back to direct introspection rather than crash.
    class UnhashableCallable:
        __hash__ = None

        def __call__(self, x):
            return x * 2

    fn = UnhashableCallable()

    with cache(Cache(ValueMemory({}), CallMemory({}))):
        wrapped = fleche()(fn)

        # Cache miss path: must run the function via the fallback.
        assert wrapped(5) == 10
        # Cache hit path: lookup must also succeed without raising.
        assert wrapped(5) == 10
        # Helper APIs that go through the same machinery.
        assert wrapped.fleche.contains(5)
        assert wrapped.fleche.load(5) == 10
