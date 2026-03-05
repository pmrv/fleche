import pytest
from fleche.call import Call
from fleche.caches import Cache
from fleche.storage import Memory

def assert_matches(tpl, target):
    assert tpl.matches(target)
    assert not Call(name="wrong", arguments=None).matches(target)

def test_call_matches():
    """Verify that Call.matches() correctly handles wildcards and values."""
    c1 = Call(name="f", arguments={"x": 1}, result=10)

    # Template matching
    assert_matches(Call(name="f", arguments=None), c1)
    assert_matches(Call(name="f", arguments={"x": 1}), c1)
    assert_matches(Call(name=None, arguments={"x": 1}), c1)
    assert_matches(Call(name="f", arguments={"x": 1}, result=10), c1)
    assert_matches(Call(name=None, result=10, arguments=None), c1)

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

    # Use same logic as test_call_matches
    assert_matches(Call(name="f", arguments=None), lazy)
    assert_matches(Call(name="f", arguments={"x": 1}), lazy)
    assert_matches(Call(name=None, result=10, arguments=None), lazy)

    assert not Call(name="f", arguments={"x": 2}).matches(lazy)
