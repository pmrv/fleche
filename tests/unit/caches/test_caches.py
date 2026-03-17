from unittest.mock import Mock, MagicMock
import pytest
from fleche import fleche, cache
from fleche.call import Call
from fleche.digest import Digest
from fleche.caches import ReadOnlyCache, CacheStack, Rejected, Cache


def test_cache_save():
    from fleche.call import Call

    values_storage = Mock()
    values_storage.save.return_value = 1
    calls_storage = Mock()
    c = Cache(values_storage, calls_storage)

    call = Call(name="test", arguments={"x": 1}, result="result")
    call.metadata = {"test": {"key": "value"}}
    c.save(call)

    # Check that the underlying cache saves values and calls
    assert values_storage.save.called
    assert calls_storage.save.called


def test_cache_load():
    values_storage = MagicMock()
    values_storage.list.return_value = [
        Digest("arg1" + "0" * 60),
        Digest("arg2" + "0" * 60),
        Digest("kwarg1" + "0" * 58),
        Digest("kwarg2" + "0" * 58),
    ]
    values_storage.load = Mock()
    calls_storage = Mock()

    calls_storage.load = Mock(
        return_value=Call(
            name="test",
            arguments={
                "arg1": Digest("arg1" + "0" * 60),
                "arg2": Digest("arg2" + "0" * 60),
                "key1": Digest("kwarg1" + "0" * 58),
                "key2": Digest("kwarg2" + "0" * 58),
            },
        )
    )
    c = Cache(values_storage, calls_storage)
    c.load("key").fetch()  # ty: ignore
    calls_storage.load.assert_called_once_with("key")
    values_storage.load.assert_any_call(Digest("arg1" + "0" * 60))
    values_storage.load.assert_any_call(Digest("arg2" + "0" * 60))
    values_storage.load.assert_any_call(Digest("kwarg1" + "0" * 58))
    values_storage.load.assert_any_call(Digest("kwarg2" + "0" * 58))


def test_cache_context_manager():
    @fleche
    def my_func(x):
        return x * 2

    # a mock cache to be the original one
    original_values = Mock()
    original_values.save.return_value = "digest_value"
    original_calls = Mock()
    original_calls.load.side_effect = KeyError
    original_cache = Cache(original_values, original_calls)

    # a mock cache to be the new one
    new_values = Mock()
    new_values.save.return_value = "digest_value"
    new_calls = Mock()
    new_calls.load.side_effect = KeyError
    new_cache = Cache(new_values, new_calls)

    # get the default cache and replace it with our mock original_cache
    default_cache = cache()
    with cache(original_cache):

        with cache(new_cache):
            assert cache() is new_cache
            my_func(2)
            new_cache.calls.load.assert_called_once()
            assert new_cache.calls.save.call_count == 1

        assert cache() is original_cache
        my_func(3)
        original_cache.calls.load.assert_called_once()
        assert original_cache.calls.save.call_count == 1

    # ensure the default cache is restored
    assert cache() is default_cache


@pytest.mark.xfail
def test_base_cache_transfer():
    values_storage = Mock()
    calls_storage = Mock()
    calls_storage.list.return_value = ["key1", "key2"]
    calls_storage.load.side_effect = ["result1", "result2"]
    c1 = Cache(values_storage, calls_storage)

    other_values_storage = Mock()
    other_calls_storage = Mock()
    c2 = Cache(other_values_storage, other_calls_storage)

    c1.transfer(c2)

    assert other_calls_storage.save.call_count == 2
    other_calls_storage.save.assert_any_call("key1", "result1")
    other_calls_storage.save.assert_any_call("key2", "result2")

    # Metadata layer removed; only calls would be transferred (feature xfailed)


def test_readonly_cache_save():
    from fleche.call import Call

    c = ReadOnlyCache(Mock())
    call = Call(name="test", arguments={"x": 1}, result="result")
    with pytest.raises(Rejected):
        c.save(call)


def test_readonly_cache_load():
    mock_cache = Mock()
    c = ReadOnlyCache(mock_cache)
    c.load("key")
    mock_cache.load.assert_called_once_with("key", lazy=True)


def test_cache_stack_save():
    from fleche.call import Call

    c1 = Mock()
    c2 = Mock()
    stack = CacheStack((c1, c2))
    call = Call(name="test", arguments={"x": 1}, result="result")
    stack.save(call)
    c1.save.assert_called_once()
    c2.save.assert_not_called()


def test_cache_stack_load_hit():
    from fleche.call import Call

    c1 = Mock()
    c1.load.side_effect = KeyError
    c2 = Mock()
    call = Call(name="test", arguments={"x": 1}, result="result")
    c2.load.return_value = call
    stack = CacheStack((c1, c2))
    result = stack.load("key")
    c1.load.assert_called_once_with("key", lazy=True)
    c2.load.assert_called_once_with("key", lazy=True)
    assert result == call


def test_cache_stack_load_miss():
    c1 = Mock()
    c1.load.side_effect = KeyError
    c2 = Mock()
    c2.load.side_effect = KeyError
    stack = CacheStack((c1, c2))


def test_cache_query_decodes_values_and_args(monkeypatch):
    """Cache.query should decode digested args and result before yielding.

    Intent: After saving a call with complex structures (lists/dicts/tuples)
    so that arguments and result are stored as digests, querying via the Cache
    wrapper must return the call with values decoded back to Python objects.
    """
    from fleche.storage import Memory
    from fleche.call import Call
    from fleche.digest import Digest

    values = Memory({})
    # Use a simple in-memory CallStorage via adapter
    calls = Memory({})
    cache = Cache(values, calls)

    # Prepare a call whose args and result are composite structures so that
    # Cache.save() persists digested forms and Cache.query() must decode them.
    original = Call(
        name="f",
        arguments={
            "a": [1, 2, 3],
            "b": {"k": 10},
        },
        metadata={},
        module=None,
        version=None,
        result=("x", 5),
    )

    # Save via Cache (this will store digests for args and result in call store)
    key = cache.save(original)

    # Build a template that matches by name only to retrieve the saved call
    tpl = Call(
        name="f", arguments=None, metadata=None, module=None, version=None, result=None
    )
    got = list(cache.query(tpl))
    assert len(got) == 1, "Wrapper query should return exactly one matching call"
    out = got[0]

    # Arguments and result should be decoded back to original Python values
    assert out.arguments["a"] == [
        1,
        2,
        3,
    ], "List argument should be decoded by Cache.query"
    assert out.arguments["b"] == {
        "k": 10
    }, "Dict argument should be decoded by Cache.query"
    assert out.result == ("x", 5), "Tuple result should be decoded by Cache.query"


def test_cachestack_query_bottom_to_top_and_dedupe():
    """CacheStack.query should query bottom-to-top and deduplicate results.

    Intent: Two caches contain overlapping calls. Bottom cache returns A and B;
    top cache returns B and C. Stack should yield A (from bottom), then B (from
    bottom; top's B is skipped), then C (from top). Order reflects bottom-to-top
    traversal and no duplicates.
    """
    from fleche.call import Call

    # Build mock caches that yield specific sequences
    bottom = Mock()
    top = Mock()

    A = Call(
        name="A", arguments={}, metadata={}, module=None, version=None, result=None
    )
    B = Call(
        name="B", arguments={}, metadata={}, module=None, version=None, result=None
    )
    C = Call(
        name="C", arguments={}, metadata={}, module=None, version=None, result=None
    )

    bottom.query.return_value = iter([A, B])
    top.query.return_value = iter([B, C])

    stack = CacheStack((bottom, top))

    # Note: CacheStack is constructed as (bottom, top); bottom-to-top means
    # bottom queried first, then top. Mocks return in their given order.
    out = list(
        stack.query(
            Call(
                name=None,
                arguments=None,
                metadata=None,
                module=None,
                version=None,
                result=None,
            )
        )
    )
    names = [c.name for c in out]
    assert names == [
        "A",
        "B",
        "C",
    ], "CacheStack.query should traverse bottom->top and deduplicate overlapping results"


def test_readonlycache_query_forwards_to_wrapped():
    """ReadOnlyCache.query should forward the call to the wrapped cache.

    Intent: Verify that ReadOnlyCache.query delegates to the inner cache and
    yields the same results.
    """
    from fleche.call import Call

    inner = Mock()
    call = Call(
        name="X", arguments={}, metadata={}, module=None, version=None, result=None
    )
    inner.query.return_value = iter([call])

    ro = ReadOnlyCache(inner)
    out = list(
        ro.query(
            Call(
                name=None,
                arguments=None,
                metadata=None,
                module=None,
                version=None,
                result=None,
            )
        )
    )
    assert out == [call], "ReadOnlyCache.query must forward results unchanged"


def test_cache_load_restores_complex_arguments_and_result():
    from fleche.storage import Memory
    from fleche.call import Call

    # Set up in‑memory storages
    values_storage = Memory({})
    calls_storage = Memory({})
    cache = Cache(values_storage, calls_storage)

    # Create a Call with list arguments and result
    original = Call(name="test_func", arguments={"arg": [1, 2, 3]}, result=[4, 5, 6])
    key = cache.save(original)
    loaded = cache.load(key)
    assert loaded.arguments["arg"] == [1, 2, 3]
    assert loaded.result == [4, 5, 6]

def test_cache_stack_push():
    c1 = Mock()
    c2 = Mock()
    stack = CacheStack((c1,))

    new_stack = stack.push(c2)

    assert isinstance(new_stack, CacheStack)
    assert new_stack.stack == (c2, c1)
