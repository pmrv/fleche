import pytest
import time
import tempfile

from fleche import fleche, cache, digest
from fleche.invocation import Invocation
from fleche.cache import Cache, ReadOnlyCache, CacheStack
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
    with cache(Cache(storage, storage)):

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

    c = Cache(Memory({}), Memory({}))
    ro_cache = ReadOnlyCache(c)

    with cache(ro_cache):
        # this should not be saved
        func(1)
        with pytest.raises(KeyError):
            ro_cache.load('2d2984056834041089b5849259a8ba42')

    # now, let's add the value to the cache and see if we can get it from there
    c.values.save('2d2984056834041089b5849259a8ba42', 1)

    with cache(ro_cache):
        # this should be loaded from ro_cache
        assert func(1) == 1


def test_fleche_cache_stack():

    @fleche
    def func(x):
        return x

    cache1 = Cache(Memory({}), Memory({}))
    cache2 = Cache(Memory({}), Memory({}))

    stack = CacheStack(stack=(cache2, cache1))

    key1 = digest(Invocation.from_call(func, 1))
    key2 = digest(Invocation.from_call(func, 2))

    with cache(stack):
        # first call, should go in cache2
        func(1)
        # assert that the value is in cache2
        # TODO: change to actually check presence of keys
        assert cache2.contains(key1)
        assert not cache1.contains(key1)

        # second call, should be loaded from cache2
        func(1)

    # now, let's add a value to cache1 and see if we can get it from there
    with cache(cache1):
        func(2)

    with cache(stack):
        # this should be loaded from cache1
        func(2)
        assert not cache2.contains(key2)
        assert cache1.contains(key2)


def test_fleche_cache_stack_context_manager():

    @fleche
    def func(x):
        return x

    cache1 = Cache(Memory({}), Memory({}))
    cache2 = Cache(Memory({}), Memory({}))

    with cache(cache1):
        with cache(cache2, stack=True):
            func(1)
            key = digest(Invocation.from_call(func, 1))
            assert cache2.contains(key)
            assert cache2.load(cache2.load(key)[0]) == 1
            assert not cache1.contains(key)

        func(2)
        key = digest(Invocation.from_call(func, 2))
        assert cache1.contains(key)

        with cache(cache2, stack=True):
            # this should be loaded from cache1
            func(2)
            assert not cache2.contains(key)
