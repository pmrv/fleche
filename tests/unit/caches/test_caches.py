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


def test_base_cache_transfer():
    from fleche.storage.memory import Memory

    c1 = Cache(values=Memory({}), _calls=Memory({}))
    c2 = Cache(values=Memory({}), _calls=Memory({}))

    call1 = Call(
        name="f1",
        arguments={"a": 1},
        result=2,
        module="test",
        version="1.0",
        metadata={},
    )
    call2 = Call(
        name="f2",
        arguments={"b": 3},
        result=4,
        module="test",
        version="1.0",
        metadata={},
    )

    c1.save(call1)
    c1.save(call2)

    c1.transfer(c2)

    assert c2.contains(str(call1.to_lookup_key()))
    assert c2.contains(str(call2.to_lookup_key()))


def test_base_cache_transfer_overwrite():
    from fleche.storage.memory import Memory

    c1 = Cache(values=Memory({}), _calls=Memory({}))
    c2 = Cache(values=Memory({}), _calls=Memory({}))

    call1 = Call(
        name="f1",
        arguments={"a": 1},
        result=2,
        module="test",
        version="1.0",
        metadata={},
    )
    # create a conflicting call in c2
    call1_conflict = Call(
        name="f1",
        arguments={"a": 1},
        result="conflict",
        module="test",
        version="1.0",
        metadata={},
    )

    # Save original to c1
    c1.save(call1)

    # Save conflict to c2
    key = c2.save(call1_conflict)

    c1.transfer(c2, overwrite=True)

    assert c2.contains(str(call1.to_lookup_key()))
    # Ensure that it was actually overwritten. The call1 should be the one in the cache.
    loaded_call = c2.load(str(call1.to_lookup_key()))
    assert loaded_call.result == 2


def test_base_cache_transfer_pop():
    from fleche.storage.memory import Memory

    c1 = Cache(values=Memory({}), _calls=Memory({}))
    c2 = Cache(values=Memory({}), _calls=Memory({}))

    call1 = Call(
        name="f1",
        arguments={"a": 1},
        result=2,
        module="test",
        version="1.0",
        metadata={},
    )
    call2 = Call(
        name="f2",
        arguments={"b": 3},
        result=4,
        module="test",
        version="1.0",
        metadata={},
    )

    c1.save(call1)
    c1.save(call2)

    c1.transfer(c2, pop=True)

    assert c2.contains(str(call1.to_lookup_key()))
    assert c2.contains(str(call2.to_lookup_key()))
    assert not c1.contains(str(call1.to_lookup_key()))
    assert not c1.contains(str(call2.to_lookup_key()))


def test_base_cache_transfer_no_overwrite_and_pop(caplog):
    """Transfer with overwrite=False and pop=True: new entries are moved,
    conflicting entries (already in target) are NOT evicted from source and a warning is logged."""
    import logging
    from fleche.storage.memory import Memory

    c1 = Cache(values=Memory({}), _calls=Memory({}))
    c2 = Cache(values=Memory({}), _calls=Memory({}))

    call1 = Call(
        name="f1",
        arguments={"a": 1},
        result=2,
        module="test",
        version="1.0",
        metadata={},
    )
    call2 = Call(
        name="f2",
        arguments={"b": 3},
        result=4,
        module="test",
        version="1.0",
        metadata={},
    )
    # call1 already exists in c2 with a different result
    call1_existing = Call(
        name="f1",
        arguments={"a": 1},
        result="existing",
        module="test",
        version="1.0",
        metadata={},
    )

    c1.save(call1)
    c1.save(call2)
    c2.save(call1_existing)

    with caplog.at_level(logging.WARNING, logger="fleche.cache"):
        c1.transfer(c2, pop=True, overwrite=False)

    # call2 should now be in c2 (was new) and evicted from c1
    assert c2.contains(str(call2.to_lookup_key()))
    assert not c1.contains(str(call2.to_lookup_key()))
    # call1 in c2 should retain the original value, not be overwritten
    assert c2.load(str(call1.to_lookup_key()), lazy=False).result == "existing"
    # call1 should still be in c1 — NOT evicted because it conflicted
    assert c1.contains(str(call1.to_lookup_key()))
    # a warning should have been emitted for the skipped eviction
    assert any("Not evicting" in m for m in caplog.messages)


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
    # avoid mocking a lazycall
    result = stack.load("key", lazy=False)
    c1.load.assert_called_once_with("key", lazy=False)
    c2.load.assert_called_once_with("key", lazy=False)
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
    values = Mock()
    calls = Mock()
    c1 = Cache(values, calls)
    c2 = Cache(values, calls)
    c3 = Cache(values, calls)

    stack1 = c1.push(c2)
    assert isinstance(stack1, CacheStack)
    assert stack1.stack == (c2, c1)

    stack2 = stack1.push(c3)
    assert isinstance(stack2, CacheStack)
    assert stack2.stack == (c3, c2, c1)
