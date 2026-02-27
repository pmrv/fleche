import pytest
from fleche.call import Call, LazyCall, LazyArguments
from fleche.caches import Cache
from fleche.storage import Memory
from fleche.digest import Digest, digest

def test_lazy_call_to_call():
    """Verify that LazyCall.to_call() reconstructs a full Call object."""
    values_storage = Memory({})
    calls_storage = Memory({})
    cache = Cache(values_storage, calls_storage)

    original = Call(name="test_func", arguments={"a": 1, "b": 2}, result=3)
    key = cache.save(original)

    lazy = cache.load(key, lazy=True)
    full_call = lazy.to_call()

    assert isinstance(full_call, Call)
    assert full_call.name == "test_func"
    assert full_call.arguments == {"a": 1, "b": 2}
    assert full_call.result == 3

def test_call_matches():
    """Verify that Call.matches() correctly handles wildcards and values."""
    c1 = Call(name="f", arguments={"x": 1}, result=10)

    # Template matching
    assert Call(name="f", arguments=None).matches(c1)
    assert Call(name="f", arguments={"x": 1}).matches(c1)
    assert Call(name=None, arguments={"x": 1}).matches(c1)
    assert Call(name="f", arguments={"x": 1}, result=10).matches(c1)

    # Non-matching
    assert not Call(name="g", arguments=None).matches(c1)
    assert not Call(name="f", arguments={"x": 2}).matches(c1)
    assert not Call(name="f", arguments={"y": 1}).matches(c1)
    assert not Call(name="f", arguments={"x": 1}, result=20).matches(c1)

def test_call_matches_lazy():
    """Verify that Call.matches() correctly handles LazyCall objects."""
    values_storage = Memory({})
    calls_storage = Memory({})
    cache = Cache(values_storage, calls_storage)

    original = Call(name="f", arguments={"x": 1}, result=10)
    key = cache.save(original)
    lazy = cache.load(key, lazy=True)

    assert Call(name="f", arguments=None).matches(lazy)
    assert Call(name="f", arguments={"x": 1}).matches(lazy)
    assert not Call(name="f", arguments={"x": 2}).matches(lazy)
