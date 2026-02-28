import pytest
from fleche.call import Call, LazyCall
from fleche.caches import Cache
from fleche.storage import Memory
from fleche.digest import digest

def test_lazy_call_reify():
    """Verify that LazyCall.reify() reconstructs a full Call object."""
    values_storage = Memory({})
    calls_storage = Memory({})
    cache = Cache(values_storage, calls_storage)

    original = Call(name="test_func", arguments={"a": 1, "b": 2}, result=3)
    key = cache.save(original)

    lazy = cache.load(key, lazy=True)
    full_call = lazy.reify()

    assert isinstance(full_call, Call)
    assert full_call.name == "test_func"
    assert full_call.arguments == {"a": 1, "b": 2}
    assert full_call.result == 3
