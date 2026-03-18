from unittest.mock import Mock
from fleche.caches import CacheStack, Cache
from fleche.call import Call
from fleche.storage import Memory
import pytest

def test_cache_stack_load_transfers_call():
    """Verify that a hit in a higher cache is transferred to the base cache during a standard load."""
    # Setup two caches
    c1 = Cache(Memory({}), Memory({}))
    c2 = Cache(Memory({}), Memory({}))

    call = Call(name="test", arguments={"x": 1}, result="result")
    key = call.to_lookup_key()

    # Save call to c2 only
    c2.save(call)

    stack = CacheStack((c1, c2))

    # Verify c1 doesn't have it
    with pytest.raises(KeyError):
        c1.load(key, lazy=False)

    # Load from stack
    res_call = stack.load(key, lazy=False)

    assert res_call.result == "result"

    # Now c1 SHOULD have it due to automatic transfer
    assert c1.contains(key)
    assert c1.load(key, lazy=False).result == "result"

def test_cache_stack_load_lazy_transfers_call():
    """Verify that a lazy hit in a higher cache is transferred to the base cache."""
    # Setup two caches
    c1 = Cache(Memory({}), Memory({}))
    c2 = Cache(Memory({}), Memory({}))

    call = Call(name="test", arguments={"x": 1}, result="result")
    key = call.to_lookup_key()

    # Save call to c2 only
    c2.save(call)

    stack = CacheStack((c1, c2))

    # Load lazy from stack
    lazy_call = stack.load(key, lazy=True)

    assert lazy_call.result == "result"

    # Now c1 SHOULD have it
    assert c1.contains(key)
    assert c1.load(key, lazy=False).result == "result"

def test_cache_stack_load_value_does_not_transfer():
    """Verify that load_value does not transfer data to the base cache."""
    c1 = Cache(Memory({}), Memory({}))
    c2 = Cache(Memory({}), Memory({}))

    val = "some_value"
    from fleche.digest import digest
    key = digest(val)

    c2.values.save(val)

    stack = CacheStack((c1, c2))

    # Verify c1 doesn't have it
    with pytest.raises(KeyError):
        c1.load_value(key)

    # Load value from stack
    res_val = stack.load_value(key)
    assert res_val == val

    # c1 should STILL not have it
    with pytest.raises(KeyError):
        c1.load_value(key)

def test_cache_stack_multi_level_transfer():
    """Verify that a hit in a 3-level stack only transfers to the base cache."""
    c1 = Cache(Memory({}), Memory({})) # base
    c2 = Cache(Memory({}), Memory({})) # intermediate
    c3 = Cache(Memory({}), Memory({})) # top

    call = Call(name="test", arguments={"x": 1}, result="result")
    key = call.to_lookup_key()

    # Save call to c3 only
    c3.save(call)

    stack = CacheStack((c1, c2, c3))

    # Verify c1 and c2 don't have it
    with pytest.raises(KeyError):
        c1.load(key, lazy=False)
    with pytest.raises(KeyError):
        c2.load(key, lazy=False)

    # Load from stack. Should hit c3 and transfer to c1 (via stack.save())
    stack.load(key, lazy=False)

    # c1 should have it
    assert c1.contains(key)
    # c2 should STILL NOT have it
    assert not c2.contains(key)
