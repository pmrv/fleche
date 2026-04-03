from unittest.mock import Mock
import pytest
from fleche.caches import CacheStack, Cache
from fleche.call import Call
from fleche.storage import Memory
from fleche.digest import digest


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
    c1 = Cache(Memory({}), Memory({}))  # base
    c2 = Cache(Memory({}), Memory({}))  # intermediate
    c3 = Cache(Memory({}), Memory({}))  # top

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
