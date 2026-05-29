import logging
from unittest.mock import Mock, MagicMock
from fleche import fleche, cache
from fleche.call import Call, DigestedCall, QueryCall
from fleche.digest import Digest
from fleche.caches import Cache, CacheStack


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
        return_value=DigestedCall(
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
    from fleche.storage.memory import ValueMemory, CallMemory

    c1 = Cache(values=ValueMemory({}), calls=CallMemory({}))
    c2 = Cache(values=ValueMemory({}), calls=CallMemory({}))

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
    from fleche.storage.memory import ValueMemory, CallMemory

    c1 = Cache(values=ValueMemory({}), calls=CallMemory({}))
    c2 = Cache(values=ValueMemory({}), calls=CallMemory({}))

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
    c2.save(call1_conflict)

    c1.transfer(c2, overwrite=True)

    assert c2.contains(str(call1.to_lookup_key()))
    # Ensure that it was actually overwritten. The call1 should be the one in the cache.
    loaded_call = c2.load(str(call1.to_lookup_key()))
    assert loaded_call.result == 2


def test_base_cache_transfer_pop():
    from fleche.storage.memory import ValueMemory, CallMemory

    c1 = Cache(values=ValueMemory({}), calls=CallMemory({}))
    c2 = Cache(values=ValueMemory({}), calls=CallMemory({}))

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
    from fleche.storage.memory import ValueMemory, CallMemory

    c1 = Cache(values=ValueMemory({}), calls=CallMemory({}))
    c2 = Cache(values=ValueMemory({}), calls=CallMemory({}))

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

    with caplog.at_level(logging.WARNING, logger="fleche.query"):
        c1.transfer(c2, pop=True, overwrite=False)

    # call2 should now be in c2 (was new) and evicted from c1
    assert c2.contains(str(call2.to_lookup_key()))
    assert not c1.contains(str(call2.to_lookup_key()))
    # call1 in c2 should retain the original value, not be overwritten
    assert c2.load(str(call1.to_lookup_key())).result == "existing"
    # call1 should still be in c1 — NOT evicted because it conflicted
    assert c1.contains(str(call1.to_lookup_key()))
    # a warning should have been emitted for the skipped conflict
    assert any("Not transferring" in m for m in caplog.messages)


def test_cache_query_decodes_values_and_args(monkeypatch):
    """Cache.query should decode digested args and result before yielding.

    Intent: After saving a call with complex structures (lists/dicts/tuples)
    so that arguments and result are stored as digests, querying via the Cache
    wrapper must return the call with values decoded back to Python objects.
    """
    from fleche.storage import ValueMemory, CallMemory
    from fleche.call import Call

    values = ValueMemory({})
    # Use a simple in-memory CallStorage via adapter
    calls = CallMemory({})
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
    cache.save(original)

    # Build a template that matches by name only to retrieve the saved call
    tpl = QueryCall(
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


def test_cache_load_restores_complex_arguments_and_result():
    from fleche.storage import ValueMemory, CallMemory
    from fleche.call import Call

    # Set up in‑memory storages
    values_storage = ValueMemory({})
    calls_storage = CallMemory({})
    cache = Cache(values_storage, calls_storage)

    # Create a Call with list arguments and result
    original = Call(name="test_func", arguments={"arg": [1, 2, 3]}, result=[4, 5, 6])
    key = cache.save(original)
    loaded = cache.load(key)
    assert loaded.arguments["arg"] == [1, 2, 3]
    assert loaded.result == [4, 5, 6]


def test_cache_query_convenience_kwargs():
    """BaseCache.query accepts QueryCall kwargs directly without constructing a QueryCall."""
    from fleche.storage.memory import ValueMemory, CallMemory

    c = Cache(values=ValueMemory({}), calls=CallMemory({}))

    call1 = Call(name="foo", arguments={"x": 1}, result=2, module="m", version=None, metadata={})
    call2 = Call(name="bar", arguments={"x": 3}, result=4, module="m", version=None, metadata={})
    c.save(call1)
    c.save(call2)

    results = list(c.query(name="foo"))
    assert len(results) == 1
    assert results[0].name == "foo"

    results = list(c.query())
    assert len(results) == 2

    results = list(c.query(QueryCall(name="bar")))
    assert len(results) == 1
    assert results[0].name == "bar"


def test_cache_query_kwargs_and_template_raises():
    """Passing both a QueryCall template and kwargs should raise TypeError."""
    import pytest
    from fleche.storage.memory import ValueMemory, CallMemory

    c = Cache(values=ValueMemory({}), calls=CallMemory({}))
    with pytest.raises(TypeError):
        c.query(QueryCall(), name="foo")


def test_load_value_plain_string_key():
    """load_value should accept a plain hex string without requiring D() wrapping."""
    from fleche.storage.memory import ValueMemory, CallMemory
    from fleche.digest import digest

    c = Cache(values=ValueMemory({}), calls=CallMemory({}))
    val = 42
    key = digest(val)  # full-length Digest

    c.values.save(val)

    # plain str (not Digest) should work without explicit D() wrapping
    assert c.load_value(str(key)) == val
    # Digest instance should still work
    assert c.load_value(key) == val


def test_load_value_short_prefix():
    """load_value should accept a short hex prefix, expanding it automatically."""
    from fleche.storage.memory import ValueMemory, CallMemory
    from fleche.digest import digest

    c = Cache(values=ValueMemory({}), calls=CallMemory({}))
    val = "hello"
    key = digest(val)

    c.values.save(val)

    short = str(key)[:8]
    assert c.load_value(short) == val


def test_hash_builtin_caches():
    """Test that all cache types respond properly to hash() builtin."""
    from fleche.caches import ReadOnlyCache, FilteredCache, RefreshingCache, SizeLimitedCache
    from fleche.storage import ValueVoid, CallVoid

    values = Mock()
    calls = Mock()
    base_cache = Cache(values, calls)

    # All these should be hashable
    assert hash(base_cache) is not None
    assert hash(ReadOnlyCache(base_cache)) is not None
    assert hash(FilteredCache(base_cache, lambda c: True)) is not None
    assert hash(RefreshingCache(base_cache)) is not None
    assert hash(CacheStack((base_cache,))) is not None

    # SizeLimitedCache with Void storage (no mutable fields)
    slc = SizeLimitedCache(ValueVoid(), CallVoid(), max_size=100)
    assert hash(slc) is not None
