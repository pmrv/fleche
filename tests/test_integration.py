import pytest
import time
import tempfile
from unittest.mock import Mock

from fleche import fleche, cache, Cache
from fleche.storage import CloudpickleFileStorage, MemoryStorage

temp = tempfile.TemporaryDirectory()
storages = [MemoryStorage({}), CloudpickleFileStorage(temp.name)]


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
