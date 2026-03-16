import concurrent.futures
import threading
import contextvars
import pytest
import fleche
from fleche.caches import Cache
from fleche.storage.memory import Memory
from fleche import state

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

def test_sticky_cache():
    """
    Verify that sticky=True works within the same thread and supports CM protocol.
    """
    mem = Memory({})
    cache1 = Cache(mem, mem)

    old_cache = state._CACHE.get()
    try:
        with fleche.cache(cache1, sticky=True):
            assert state._CACHE.get() is cache1

        assert state._CACHE.get() is cache1 # Still there because sticky

        my_func(300)
        assert cache1.contains(my_func.digest(300))
    finally:
        state._CACHE.set(old_cache)

def test_sticky_meta():
    """
    Verify that sticky=True works for metadata.
    """
    from fleche.metadata import Tags

    old_meta = state._METADATA.get()
    try:
        fleche.tags(sticky=True, foo="bar")
        active_meta = state._METADATA.get()
        assert any(isinstance(m, Tags) and m.tags == {"foo": "bar"} for m in active_meta)
    finally:
        state._METADATA.set(old_meta)

def test_sticky_cache_stack():
    """
    Verify that sticky=True works with stack=True.
    """
    mem1 = Memory({})
    cache1 = Cache(mem1, mem1)

    old_cache = state._CACHE.get()
    try:
        fleche.cache(cache1, stack=True, sticky=True)
        assert isinstance(state._CACHE.get(), fleche.caches.CacheStack)
        assert state._CACHE.get().stack[0] is cache1
    finally:
        state._CACHE.set(old_cache)
