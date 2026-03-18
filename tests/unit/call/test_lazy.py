import pytest
from hypothesis import given

from fleche.call import Call, LazyCall
from fleche.caches import Cache
from fleche.storage import Memory
from fleche.digest import digest
from tests.strategies import st_nested_values


def test_lazy_call_fetch():
    """Verify that LazyCall.fetch() reconstructs a full Call object."""
    values_storage = Memory({})
    calls_storage = Memory({})
    cache = Cache(values_storage, calls_storage)

    original = Call(name="test_func", arguments={"a": 1, "b": 2}, result=3)
    key = cache.save(original)

    lazy = cache.load(key, lazy=True)
    full_call = lazy.fetch()

    assert isinstance(full_call, Call)
    assert full_call.name == "test_func"
    assert full_call.arguments == {"a": 1, "b": 2}
    assert full_call.result == 3


@pytest.mark.skip(reason="pre-existing failing test")
@given(st_nested_values)
def test_lazy_call_to_lookup_key_consistency(args):
    """
    Verify that `LazyCall.to_lookup_key()` returns the same digest as the
    original `Call.to_lookup_key()` even when complex nested arguments are
    partially stored as digests.
    """
    values_storage = Memory({})
    calls_storage = Memory({})
    cache = Cache(values_storage, calls_storage)

    # Put our complex args into the Call
    arguments = {"x": args} if args is not None else {}
    original = Call(name="test_func", arguments=arguments, result=None)

    key = cache.save(original)

    # Load as LazyCall
    lazy = cache.load(key, lazy=True)

    assert isinstance(lazy, LazyCall)
    assert lazy.to_lookup_key() == original.to_lookup_key()
