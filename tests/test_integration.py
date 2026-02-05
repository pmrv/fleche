import pytest
import time
import tempfile
from unittest.mock import Mock

from fleche import fleche, cache, Cache, ReadOnlyCache, CacheStack
from fleche.storage import CloudpickleFile, Memory

temp = tempfile.TemporaryDirectory()
storages = [Memory({}), CloudpickleFile(temp.name)]


@fleche
def slow_function_impl(x):
    time.sleep(1)
    return x * 2


@fleche
def fib_impl(n):
    if n < 2:
        return n
    return fib_impl(n-1) + fib_impl(n-2)


functions_to_test = [
    (slow_function_impl, 2),
    (fib_impl, 15)
]


@pytest.mark.parametrize("storage", storages)
@pytest.mark.parametrize("func, arg", functions_to_test)
def test_fleche_performance(storage, func, arg):
    with cache(Cache(storage=storage, metadata=Mock())):

        start_time = time.time()
        func(arg)
        first_call_time = time.time() - start_time

        start_time = time.time()
        func(arg)
        second_call_time = time.time() - start_time

        assert second_call_time < first_call_time / 2


def test_fleche_readonly_cache():

    @fleche
    def func(x):
        return x

    c = Cache(storage=Memory({}), metadata=Mock())
    ro_cache = ReadOnlyCache(c)

    with cache(ro_cache):
        # this should not be saved
        func(1)
        with pytest.raises(KeyError):
            ro_cache.load('2d2984056834041089b5849259a8ba42')

    # now, let's add the value to the cache and see if we can get it from there
    c.storage.save('2d2984056834041089b5849259a8ba42', 1)

    with cache(ro_cache):
        # this should be loaded from ro_cache
        assert func(1) == 1


def test_fleche_cache_stack():

    @fleche
    def func(x):
        return x

    cache1 = Cache(storage=Memory({}), metadata=Mock())
    cache2 = Cache(storage=Memory({}), metadata=Mock())

    stack = CacheStack(stack=(cache2, cache1))

    with cache(stack):
        # first call, should go in cache2
        func(1)
        # assert that the value is in cache2
        assert len(cache2.storage.list()) == 1
        assert cache2.storage.load(list(cache2.storage.list())[0]) == 1
        # assert that the value is not in cache1
        assert len(cache1.storage.list()) == 0

        # second call, should be loaded from cache2
        func(1)

    # now, let's add a value to cache1 and see if we can get it from there
    with cache(cache1):
        func(2)

    with cache(stack):
        # this should be loaded from cache1
        assert func(2) == 2
        # size of the other cache should not increase, otherwise last call got added to it
        assert len(cache2.storage.list()) == 1


def test_fleche_cache_stack_context_manager():

    @fleche
    def func(x):
        return x

    cache1 = Cache(storage=Memory({}), metadata=Mock())
    cache2 = Cache(storage=Memory({}), metadata=Mock())

    with cache(cache1):
        with cache(cache2, stack=True):
            # first call, should go in cache2
            func(1)
            # assert that the value is in cache2
            assert len(cache2.storage.list()) == 1
            assert cache2.storage.load(list(cache2.storage.list())[0]) == 1
            # assert that the value is not in cache1
            assert len(cache1.storage.list()) == 0

            # second call, should be loaded from cache2
            func(1)

        # third call, should go in cache1
        func(2)
        assert len(cache1.storage.list()) == 1

        with cache(cache2, stack=True):
            # this should be loaded from cache1
            assert func(2) == 2
            # size of the other cache should not increase, otherwise last call got added to it
            assert len(cache2.storage.list()) == 1
