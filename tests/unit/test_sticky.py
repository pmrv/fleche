
import pytest
from fleche import cache, meta, tags, project, fleche
from fleche.caches import Cache, CacheStack
from fleche.storage import Memory
from fleche.metadata import MetaData, Call

@pytest.fixture(autouse=True)
def reset_state():
    # ContextVars are local to the thread/task, but for tests we might want to ensure a clean start
    # Actually ContextVars in same thread persist across tests if not careful.
    # However, pytest usually runs tests in a way that might share the same thread.
    # Let's manually reset to defaults if possible, but state.py doesn't expose the tokens.
    # A better way is to use a fixture that saves the current state and restores it.
    import fleche.state as state
    cache_token = state._CACHE.set(state.load_cache_config())
    meta_token = state._METADATA.set(state.load_default_metadata())
    yield
    state._CACHE.reset(cache_token)
    state._METADATA.reset(meta_token)

def test_cache_sticky():
    c1 = Cache(Memory({}), Memory({}))
    returned = cache(c1, sticky=True)
    assert returned is c1
    assert cache() is c1

def test_cache_sticky_stack():
    c_base = cache()
    c1 = Cache(Memory({}), Memory({}))
    cache(c1, sticky=True, stack=True)
    assert isinstance(cache(), CacheStack)
    assert cache().stack[0] is c1
    assert cache().stack[1] is c_base

def test_tags_sticky():
    @fleche
    def func(x): return x

    c = Cache(Memory({}), Memory({}))
    with cache(c):
        tags(sticky=True, version="1.2.3")
        func(1)
        call = c.calls.load(func.digest(1))
        assert call.metadata["tags"]["version"] == "1.2.3"

        func(2)
        call = c.calls.load(func.digest(2))
        assert call.metadata["tags"]["version"] == "1.2.3"

def test_project_sticky():
    @fleche
    def func(x): return x

    c = Cache(Memory({}), Memory({}))
    with cache(c):
        project("my_project", sticky=True)
        func(1)
        call = c.calls.load(func.digest(1))
        assert call.metadata["tags"]["project"] == "my_project"

def test_meta_sticky_custom():
    class MyMeta(MetaData):
        name = "custom"
        keys = {"val": int}
        def pre(self, call: Call): return {"val": 42}

    m = MyMeta()
    meta(m, sticky=True)

    @fleche
    def func(x): return x

    c = Cache(Memory({}), Memory({}))
    with cache(c):
        func(1)
        call = c.calls.load(func.digest(1))
        assert call.metadata["custom"]["val"] == 42

def test_sticky_interaction_with_context_manager():
    @fleche
    def func(x): return x
    c = Cache(Memory({}), Memory({}))

    tags(sticky=True, global_tag="active")

    with cache(c):
        with tags(local_tag="present"):
            func(1)
            call = c.calls.load(func.digest(1))
            assert call.metadata["tags"]["global_tag"] == "active"
            assert call.metadata["tags"]["local_tag"] == "present"

        func(2)
        call = c.calls.load(func.digest(2))
        assert call.metadata["tags"]["global_tag"] == "active"
        assert "local_tag" not in call.metadata["tags"]
