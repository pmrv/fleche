import pytest
from unittest.mock import Mock, call
from fleche.call import Call, DelayedCall, DelayedArguments
from fleche.caches import Cache
from fleche.storage import Memory
from fleche.digest import Digest, digest

def test_delayed_call_load():
    values_storage = Memory({})
    calls_storage = Memory({})
    cache = Cache(values_storage, calls_storage)

    original = Call(name="test_func", arguments={"a": 1, "b": 2}, result=3)
    key = cache.save(original)

    # Load with delayed=True
    delayed = cache.load(key, delayed=True)
    assert isinstance(delayed, DelayedCall)
    assert delayed.name == "test_func"

    # Check that it's NOT yet loaded
    # We can mock load_value and _handle_args_load on the cache to verify
    cache._handle_args_load = Mock(side_effect=cache._handle_args_load)
    cache.load_value = Mock(side_effect=cache.load_value)

    # Accessing arguments
    args = delayed.arguments
    assert isinstance(args, DelayedArguments)
    assert cache._handle_args_load.call_count == 0

    # Access one argument
    val_a = args["a"]
    assert val_a == 1
    assert cache._handle_args_load.call_count == 1
    cache._handle_args_load.assert_called_with(digest(1))

    # Access another argument
    val_b = args["b"]
    assert val_b == 2
    assert cache._handle_args_load.call_count == 2

    # Accessing result
    # Note: load_value might have been called by _handle_args_load above
    # so we check the count relative to what it was
    load_value_count_before = cache.load_value.call_count
    res = delayed.result
    assert res == 3
    assert cache.load_value.call_count == load_value_count_before + 1
    cache.load_value.assert_called_with(digest(3))

def test_delayed_call_to_lookup_key():
    values_storage = Memory({})
    calls_storage = Memory({})
    cache = Cache(values_storage, calls_storage)

    original = Call(name="test_func", arguments={"a": [1, 2]}, result=42)
    key = cache.save(original)

    delayed = cache.load(key, delayed=True)
    assert delayed.to_lookup_key() == key

def test_delayed_call_digest():
    values_storage = Memory({})
    calls_storage = Memory({})
    cache = Cache(values_storage, calls_storage)

    original = Call(name="test_func", arguments={"a": 1}, result=2)
    key = cache.save(original)

    # We need to get the original call as it was saved (with digests)
    # because digest(original) is DIFFERENT from digest(saved_call) if original has actual values
    # and saved_call has digests.
    saved_call = calls_storage.load(key)

    delayed = cache.load(key, delayed=True)
    assert digest(delayed) == digest(saved_call)

def test_cache_query_delayed():
    values_storage = Memory({})
    calls_storage = Memory({})
    cache = Cache(values_storage, calls_storage)

    cache.save(Call(name="f", arguments={"x": 1}, result=10))
    cache.save(Call(name="f", arguments={"x": 2}, result=20))

    tpl = Call(name="f", arguments=None, metadata=None, module=None, version=None, result=None)

    # Query with delayed=True
    results = list(cache.query(tpl, delayed=True))
    assert len(results) == 2
    for r in results:
        assert isinstance(r, DelayedCall)
        assert r.name == "f"

def test_delayed_call_frozen():
    from dataclasses import FrozenInstanceError
    delayed = DelayedCall(name="f", _arguments={}, _result=None, _cache=None)
    with pytest.raises(FrozenInstanceError):
        delayed.name = "g"

def test_delayed_arguments_mapping():
    cache = Mock()
    cache._handle_args_load.side_effect = lambda x: f"loaded_{x}"
    arg_digests = {"a": "dig_a", "b": "dig_b"}
    args = DelayedArguments(cache, arg_digests)

    assert len(args) == 2
    assert set(args) == {"a", "b"}
    assert args["a"] == "loaded_dig_a"
    assert args["b"] == "loaded_dig_b"
    assert "a" in args
    assert "c" not in args
    assert list(args.items()) == [("a", "loaded_dig_a"), ("b", "loaded_dig_b")]
