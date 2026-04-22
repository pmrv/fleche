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


def test_query_call_matches_metadata():
    """Verify QueryCall.matches() metadata filtering covers all branches.

    Branches exercised:
      * metadata name missing on the candidate → reject
      * filters=None as wildcard on a present metadata name → accept
      * filters value equal to stored → accept
      * filters value different from stored → reject
      * filters value is None (presence-only): key present → accept
      * filters value is None (presence-only): key absent → reject
    """
    c = Call(
        name="f",
        arguments={"x": 1},
        metadata={"runtime": {"walltime": 1.0, "host": "nuc"}},
        result=10,
    )

    # filters=None is a wildcard on a present metadata name
    assert QueryCall(metadata={"runtime": None}).matches(c)

    # value equality
    assert QueryCall(metadata={"runtime": {"walltime": 1.0}}).matches(c)
    assert not QueryCall(metadata={"runtime": {"walltime": 2.0}}).matches(c)

    # presence-only filter via None value
    assert QueryCall(metadata={"runtime": {"host": None}}).matches(c)
    assert not QueryCall(metadata={"runtime": {"missing": None}}).matches(c)

    # required metadata name absent on the candidate → reject
    assert not QueryCall(metadata={"tags": None}).matches(c)


def test_query_call_matches_lazy():
    """Verify that QueryCall.matches() correctly handles LazyCall objects."""
    values_storage = ValueMemory({})
    calls_storage = CallMemory({})
    cache = Cache(values_storage, calls_storage)

    original = Call(name="f", arguments={"x": 1}, result=10)
    key = cache.save(original)
    lazy = cache.load(key, lazy=True)

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
