
import pytest
from fleche import cache, meta, tags, project, fleche
from fleche.caches import Cache, CacheStack
from fleche.storage import Memory
from fleche.metadata import MetaData, Call

@pytest.fixture(autouse=True)
def reset_state():
    import fleche.state as state
    cache_token = state.cache.set(state.load_cache_config())
    meta_token = state.meta.set(state.load_default_metadata())
    yield
    state.cache.reset(cache_token)
    state.meta.reset(meta_token)

def test_cache_stick_pluck():
    c1 = Cache(Memory({}), Memory({}))
    original_cache = cache()

    token = cache(c1)
    token.stick()
    assert cache() is c1

    token.pluck()
    assert cache() is original_cache

def test_cache_stack_stick():
    c_base = cache()
    c1 = Cache(Memory({}), Memory({}))
    cache(c1, stack=True).stick()

    current = cache()
    assert isinstance(current, CacheStack)
    assert current.stack[0] is c1
    assert current.stack[1] is c_base

def test_tags_stick():
    @fleche
    def func(x): return x

    c = Cache(Memory({}), Memory({}))
    with cache(c):
        tags(version="1.2.3").stick()
        func(1)
        call = c.calls.load(func.digest(1))
        assert call.metadata["tags"]["version"] == "1.2.3"

        func(2)
        call = c.calls.load(func.digest(2))
        assert call.metadata["tags"]["version"] == "1.2.3"

def test_project_stick():
    @fleche
    def func(x): return x

    c = Cache(Memory({}), Memory({}))
    with cache(c):
        project("my_project").stick()
        func(1)
        call = c.calls.load(func.digest(1))
        assert call.metadata["tags"]["project"] == "my_project"

def test_meta_stick_custom():
    class MyMeta(MetaData):
        name = "custom"
        keys = {"val": int}
        def pre(self, call: Call): return {"val": 42}

    m = MyMeta()
    meta(m).stick()

    @fleche
    def func(x): return x

    c = Cache(Memory({}), Memory({}))
    with cache(c):
        func(1)
        call = c.calls.load(func.digest(1))
        assert call.metadata["custom"]["val"] == 42

def test_interaction_with_context_manager():
    @fleche
    def func(x): return x
    c = Cache(Memory({}), Memory({}))

    tags(global_tag="active").stick()

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

def test_decorator_usage():
    @fleche
    def func(x): return x
    c = Cache(Memory({}), Memory({}))

    @tags(dec_tag="decorated")
    def run_decorated():
        with cache(c):
            func(1)
            call = c.calls.load(func.digest(1))
            assert call.metadata["tags"]["dec_tag"] == "decorated"

    run_decorated()

    with cache(c):
        func(2)
        call = c.calls.load(func.digest(2))
        assert "dec_tag" not in call.metadata.get("tags", {})

def test_dynamic_stacking_decorator():
    @fleche
    def func(x): return x
    c = Cache(Memory({}), Memory({}))

    @tags(inner="value")
    def my_decorated_func(val):
        func(val)

    with cache(c):
        with tags(outer="context"):
            my_decorated_func(1)
            call = c.calls.load(func.digest(1))
            assert call.metadata["tags"]["outer"] == "context"
            assert call.metadata["tags"]["inner"] == "value"

        my_decorated_func(2)
        call = c.calls.load(func.digest(2))
        assert "outer" not in call.metadata["tags"]
        assert call.metadata["tags"]["inner"] == "value"

def test_cache_reset_method():
    c1 = Cache(Memory({}), Memory({}))
    original_cache = cache()

    token = cache(c1).stick()
    assert cache() is c1

    cache.reset(token)
    assert cache() is original_cache

def test_meta_reset_method():
    original_meta = meta()

    class Dummy(MetaData):
        name = "dummy"
        keys = {}

        def pre(self, call: Call):
            return {}

    m = Dummy()
    token = meta(m).stick()
    assert m in meta.get()

    meta.reset(token)
    assert meta() == original_meta
