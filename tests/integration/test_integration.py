import pytest
import time
import tempfile

from fleche import fleche, cache
from fleche.digest import digest
from fleche.caches import Cache, ReadOnlyCache, CacheStack
from fleche.call import Call
from fleche.storage import CloudpickleFile, Memory
from fleche.storage.sql import Sql

temp = tempfile.TemporaryDirectory()
storages = [
    (Memory({}), Memory({})),
    (CloudpickleFile(temp.name), CloudpickleFile(temp.name)),
    (Memory({}), Sql()),
]


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


@pytest.mark.parametrize("values_storage, calls_storage", storages)
@pytest.mark.parametrize("func, arg", functions_to_test)
def test_fleche_performance(values_storage, calls_storage, func, arg):
    with cache(Cache(values=values_storage, calls=calls_storage)):

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
            func.load(1)

    # add the call to underlying cache
    with cache(c):
        func(1)

    with cache(ro_cache):
        # this should be loaded from ro_cache
        try:
            func.load(1)
        except KeyError:
            assert False, "Failed to load value from underlying cache!"


def test_fleche_cache_stack():

    @fleche
    def func(x):
        return x

    cache1 = Cache(Memory({}), Memory({}))
    cache2 = Cache(Memory({}), Memory({}))

    stack = CacheStack(stack=(cache2, cache1))

    key1 = func.digest(1)
    key2 = func.digest(2)

    with cache(stack):
        # first call, should go in cache2
        func(1)
        # assert that the value is in cache2
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
            key = func.digest(1)
            assert cache2.contains(key)
            assert cache2.load(key).result == 1
            assert not cache1.contains(key)

        func(2)
        key = func.digest(2)
        assert cache1.contains(key)

        with cache(cache2, stack=True):
            # this should be loaded from cache1
            func(2)
            assert not cache2.contains(key)


@pytest.mark.parametrize(
    "backend",
    [
        "memory_memory",   # values=Memory, calls=Memory
        "memory_sql",      # values=Memory, calls=Sql (in-memory SQLite)
    ],
)
def test_cache_hit_returns_materialized_value(backend):
    if backend == "memory_memory":
        values = Memory({})
        calls = Memory({})
    elif backend == "memory_sql":
        values = Memory({})
        calls = Sql()  # in-memory SQLite by default
    else:
        raise AssertionError("unknown backend")

    c = Cache(values, calls)

    @fleche
    def twice(x):
        return x * 2

    with cache(c):
        # miss -> compute and store
        r1 = twice(5)
        assert r1 == 10

        # hit -> must return original python value, not digest string
        r2 = twice(5)
        assert r2 == 10
        assert r2 != digest(10)
