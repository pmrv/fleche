import concurrent.futures
import contextvars
import fleche

@fleche.fleche
def my_func(x):
    return x + 1

def test_threadpool_inheritance_failure(cache_fixture):
    """
    Demonstrate that standard fleche.cache() context manager
    does not propagate to ThreadPoolExecutor in this environment.
    """
    with fleche.cache(cache_fixture):
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            # We expect this NOT to be in cache_fixture if inheritance fails
            future = executor.submit(my_func, 100)
            future.result()

            assert not cache_fixture.contains(my_func.digest(100))

def test_threadpool_explicit_context_propagation(cache_fixture):
    """
    Demonstrate that explicit context propagation works.
    """
    with fleche.cache(cache_fixture):
        ctx = contextvars.copy_context()
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(ctx.run, my_func, 200)
            future.result()

            assert cache_fixture.contains(my_func.digest(200))
