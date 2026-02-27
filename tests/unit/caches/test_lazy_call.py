import pytest
from unittest.mock import Mock, call
from fleche.call import Call, LazyCall, LazyArguments
from fleche.caches import Cache
from fleche import cache as cache_context
from fleche.storage import Memory
from fleche.digest import Digest, digest

def test_lazy_call_load():
    """Verify that LazyCall defers loading of arguments and results until they are accessed."""
    values_storage = Memory({})
    calls_storage = Memory({})
    cache = Cache(values_storage, calls_storage)

    original = Call(name="test_func", arguments={"a": 1, "b": 2}, result=3)
    key = cache.save(original)

    # Load with lazy=True
    lazy = cache.load(key, lazy=True)
    assert isinstance(lazy, LazyCall)
    assert lazy.name == "test_func"

    # Check that it's NOT yet loaded. We mock the internal load handlers to track calls.
    cache._handle_args_load = Mock(side_effect=cache._handle_args_load)
    cache.load_value = Mock(side_effect=cache.load_value)

    # Accessing arguments property returns a proxy, doesn't trigger load yet.
    args = lazy.arguments
    assert isinstance(args, LazyArguments)
    assert cache._handle_args_load.call_count == 0

    # Accessing an individual argument should trigger exactly one load for that argument.
    val_a = args["a"]
    assert val_a == 1
    assert cache._handle_args_load.call_count == 1
    cache._handle_args_load.assert_called_with(digest(1))

    # Accessing another argument triggers another load.
    val_b = args["b"]
    assert val_b == 2
    assert cache._handle_args_load.call_count == 2

    # Accessing result should trigger its own load.
    # Note: load_value might have been called by _handle_args_load if arguments were complex,
    # but here they are simple ints.
    load_value_count_before = cache.load_value.call_count
    res = lazy.result
    assert res == 3
    assert cache.load_value.call_count == load_value_count_before + 1
    cache.load_value.assert_called_with(digest(3))

def test_lazy_call_to_lookup_key():
    """Verify that LazyCall produces the same lookup key as the original Call."""
    values_storage = Memory({})
    calls_storage = Memory({})
    cache = Cache(values_storage, calls_storage)

    original = Call(name="test_func", arguments={"a": [1, 2]}, result=42)
    key = cache.save(original)

    lazy = cache.load(key, lazy=True)
    assert lazy.to_lookup_key() == key

def test_lazy_call_digest():
    """Verify that LazyCall has the same digest as the equivalent Call object."""
    values_storage = Memory({})
    calls_storage = Memory({})
    cache = Cache(values_storage, calls_storage)

    # Case 1: Simple values
    original = Call(name="test_func", arguments={"a": 1}, result=2)
    key = cache.save(original)

    # The saved call in storage has Digests.
    saved_call = calls_storage.load(key)

    lazy = cache.load(key, lazy=True)

    # 1. LazyCall digest should match the saved Call (which has Digests)
    assert digest(lazy) == digest(saved_call)

    # 2. LazyCall digest should also match the original Call (which has raw values)
    # This is because digest(val) == digest(Digest(digest(val)))
    assert digest(lazy) == digest(original)

    # Case 2: LazyArguments digest should match dict digest
    assert digest(lazy.arguments) == digest(original.arguments)

def test_cache_query_lazy():
    """Verify that Cache.query(lazy=True) yields LazyCall instances."""
    values_storage = Memory({})
    calls_storage = Memory({})
    cache = Cache(values_storage, calls_storage)

    cache.save(Call(name="f", arguments={"x": 1}, result=10))
    cache.save(Call(name="f", arguments={"x": 2}, result=20))

    tpl = Call(name="f", arguments=None, metadata=None, module=None, version=None, result=None)

    # Query with lazy=True
    results = list(cache.query(tpl, lazy=True))
    assert len(results) == 2
    for r in results:
        assert isinstance(r, LazyCall)
        assert r.name == "f"

def test_lazy_call_frozen():
    """Verify that LazyCall is immutable."""
    from dataclasses import FrozenInstanceError
    lazy = LazyCall(name="f", _arguments={}, _result=None, _cache=None)
    with pytest.raises(FrozenInstanceError):
        lazy.name = "g"

def test_lazy_arguments_mapping():
    """Verify that LazyArguments implements the Mapping interface correctly."""
    cache = Mock()
    cache._handle_args_load.side_effect = lambda x: f"loaded_{x}"
    arg_digests = {"a": "dig_a", "b": "dig_b"}
    args = LazyArguments(cache, arg_digests)

    assert len(args) == 2
    assert set(args) == {"a", "b"}
    assert args["a"] == "loaded_dig_a"
    assert args["b"] == "loaded_dig_b"
    assert "a" in args
    assert "c" not in args
    assert list(args.items()) == [("a", "loaded_dig_a"), ("b", "loaded_dig_b")]

def test_lazy_call_maintains_cache_reference():
    """Verify that a LazyCall retains its original cache even if the active context changes.

    This ensures that when values are eventually loaded, they come from the correct storage.
    """
    # Set up first cache and save a value
    cache1 = Cache(Memory({}), Memory({}))
    key = cache1.save(Call(name="f", arguments={"x": "val1"}, result="res1"))

    # Obtain a lazy call from cache1
    lazy = cache1.load(key, lazy=True)

    # Set up second cache
    cache2 = Cache(Memory({}), Memory({}))

    # Change active cache context
    with cache_context(cache2):
        # Accessing values should still hit cache1 because lazy call holds a reference to it
        assert lazy.arguments["x"] == "val1"
        assert lazy.result == "res1"

        # Verify cache2 was not touched
        assert len(list(cache2.values.list())) == 0

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
