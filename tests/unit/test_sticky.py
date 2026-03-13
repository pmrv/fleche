import fleche as fl
from fleche.storage import Memory
from fleche.caches import Cache
from fleche.metadata import Tags
import pytest
import concurrent.futures

def test_sticky_cache():
    c1 = Cache(Memory({}), Memory({}))
    c2 = Cache(Memory({}), Memory({}))

    # Default cache
    initial_cache = fl.cache.get()

    # Permanent switch
    returned = fl.cache(c1, sticky=True)
    assert fl.cache.get() is c1
    assert returned is c1

    # Temporary switch within sticky
    with fl.cache(c2):
        assert fl.cache.get() is c2

    assert fl.cache.get() is c1

    # Restore for other tests
    fl.cache.set(initial_cache)

def test_sticky_tags():
    initial_meta = fl.meta.get()

    # Permanent tags
    fl.tags(sticky=True, project="secret")
    assert any(isinstance(m, Tags) and m.tags.get("project") == "secret" for m in fl.meta)

    # Stacked temporary tags
    with fl.tags(user="jules"):
        assert any(isinstance(m, Tags) and m.tags.get("project") == "secret" for m in fl.meta)
        assert any(isinstance(m, Tags) and m.tags.get("user") == "jules" for m in fl.meta)

    # Back to sticky state
    assert any(isinstance(m, Tags) and m.tags.get("project") == "secret" for m in fl.meta)
    assert not any(isinstance(m, Tags) and m.tags.get("user") == "jules" for m in fl.meta)

    # Cleanup
    fl.meta.set(initial_meta)

def test_cache_proxy_methods():
    c = Cache(Memory({}), Memory({}))
    fl.cache.set(c)

    @fl.fleche
    def add(a, b):
        return a + b

    add(1, 2)

    # Test that fl.cache.query works directly
    results = list(fl.cache.query(add.call(1, 2)))
    assert len(results) == 1
    assert results[0].result == 3

def test_meta_proxy_sequence():
    initial_meta = fl.meta.get()
    fl.meta.set(())

    fl.tags(sticky=True, a=1)
    fl.tags(sticky=True, b=2)

    assert len(fl.meta) == 2
    assert isinstance(fl.meta[0], Tags)
    assert fl.meta[0].tags["a"] == 1

    # Cleanup
    fl.meta.set(initial_meta)

def test_thread_safety_sticky():
    """Sticky changes in one thread should not affect another thread."""
    c_main = fl.cache.get()
    c_thread = Cache(Memory({}), Memory({}))

    def worker():
        fl.cache(c_thread, sticky=True)
        return fl.cache.get()

    with concurrent.futures.ThreadPoolExecutor() as executor:
        future = executor.submit(worker)
        thread_cache = future.result()

    assert thread_cache is c_thread
    assert fl.cache.get() is c_main
