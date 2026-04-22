from fleche.call import Call, QueryCall
from fleche.caches import Cache
from fleche.storage import ValueMemory, CallMemory


def test_query_call_matches():
    """Verify that QueryCall.matches() correctly handles wildcards and values."""
    c1 = Call(name="f", arguments={"x": 1}, result=10)

    # Template matching
    assert QueryCall(name="f", arguments=None).matches(c1)
    assert QueryCall(name="f", arguments={"x": 1}).matches(c1)
    assert QueryCall(name=None, arguments={"x": 1}).matches(c1)
    assert QueryCall(name="f", arguments={"x": 1}, result=10).matches(c1)
    assert QueryCall(name=None, result=10, arguments=None).matches(c1)

    # Non-matching
    assert not QueryCall(name="g", arguments=None).matches(c1)
    assert not QueryCall(name="f", arguments={"x": 2}).matches(c1)
    assert not QueryCall(name="f", arguments={"y": 1}).matches(c1)
    assert not QueryCall(name="f", arguments={"x": 1}, result=20).matches(c1)


def test_query_call_matches_lazy():
    """Verify that QueryCall.matches() correctly handles LazyCall objects."""
    values_storage = ValueMemory({})
    calls_storage = CallMemory({})
    cache = Cache(values_storage, calls_storage)

    original = Call(name="f", arguments={"x": 1}, result=10)
    key = cache.save(original)
    lazy = cache.load(key)

    # Template matching
    assert QueryCall(name="f", arguments=None).matches(lazy)
    assert QueryCall(name="f", arguments={"x": 1}).matches(lazy)
    assert QueryCall(name=None, arguments={"x": 1}).matches(lazy)
    assert QueryCall(name="f", arguments={"x": 1}, result=10).matches(lazy)
    assert QueryCall(name=None, result=10, arguments=None).matches(lazy)

    # Non-matching
    assert not QueryCall(name="g", arguments=None).matches(lazy)
    assert not QueryCall(name="f", arguments={"x": 2}).matches(lazy)
    assert not QueryCall(name="f", arguments={"y": 1}).matches(lazy)
    assert not QueryCall(name="f", arguments={"x": 1}, result=20).matches(lazy)
