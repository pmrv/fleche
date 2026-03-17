import concurrent.futures
import contextvars
import fleche
from fleche.caches import Cache
from fleche.storage.memory import Memory

@fleche.fleche
def my_func(x):
    return x + 1

def test_threadpool_inheritance_failure():
    """
    Demonstrate that standard fleche.cache() context manager
    does not propagate to ThreadPoolExecutor in this environment.
    """
    mem = Memory({})
    cache1 = Cache(mem, mem)

    with fleche.cache(cache1):
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            # We expect this NOT to be in cache1 if inheritance fails
            future = executor.submit(my_func, 100)
            future.result()

            assert not cache1.contains(my_func.digest(100))

def test_threadpool_explicit_context_propagation():
    """
    Demonstrate that explicit context propagation works.
    """
    mem = Memory({})
    cache1 = Cache(mem, mem)

    with fleche.cache(cache1):
        ctx = contextvars.copy_context()
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(ctx.run, my_func, 200)
            future.result()

            assert cache1.contains(my_func.digest(200))
