import pytest
import logging
from typing import Any
from fleche.storage import memory
from fleche.caches import Cache
from fleche import fleche, Ignored, Required
import fleche.state as state
from fleche.caches import BaseCache


@pytest.fixture
def memory_cache():
    values_storage = memory.Memory(storage={})
    calls_storage = memory.Memory(storage={})
    cache = Cache(values=values_storage, _calls=calls_storage)
    token = state._CACHE.set(cache)
    yield calls_storage
    state._CACHE.reset(token)

@fleche(ignore='b')
def ignored_via_decorator(a, b):
    return a + b

@fleche
def ignored_via_hint(a, b: Ignored):
    return a + b

@pytest.mark.parametrize("foo", [ignored_via_decorator, ignored_via_hint])
def test_ignored_invariant(memory_cache, foo):
    calls_storage = memory_cache

    foo(1, 2)
    assert len(calls_storage.storage) == 1
    key1 = foo.digest(1, 2)

    foo(1, 3)
    assert len(calls_storage.storage) == 1
    key2 = foo.digest(1, 3)

    assert key1 == key2

@fleche(require='b')
def required_via_decorator(a, b=None):
    return a + (b or 0)

@fleche
def required_via_hint(a, b: Required[Any] = None):
    return a + (b or 0)

@pytest.mark.parametrize("bar", [required_via_decorator, required_via_hint])
def test_required_invariant(memory_cache, caplog, bar):
    calls_storage = memory_cache

    caplog.clear()
    with caplog.at_level(logging.WARNING):
        bar(1)
        assert "Missing required keyword arguments" in caplog.text
        assert len(calls_storage.storage) == 0

    caplog.clear()
    bar(1, b=2)
    assert len(calls_storage.storage) == 1
    assert "Missing required keyword arguments" not in caplog.text

def test_ignored_hint_generic(memory_cache):
    calls_storage = memory_cache

    @fleche
    def foo(a, b: Ignored[int]):
        return a + b

    foo(1, 2)
    assert len(calls_storage.storage) == 1

    foo(1, 3)
    assert len(calls_storage.storage) == 1
    # FIXME: how to get load count?
    # assert memory_cache.load_count >= 1

def test_required_hint_positional_warning(memory_cache, caplog):
    caplog.clear()
    with caplog.at_level(logging.WARNING):
        @fleche
        def foo(a: Required, /):
            return a
        assert "is marked as Required but is positional-only" in caplog.text

def test_required_hint_positional_skip(memory_cache, caplog):
    calls_storage = memory_cache

    @fleche
    def foo(a: Required, b=1):
        return a + b

    caplog.clear()
    with caplog.at_level(logging.WARNING):
        foo(2) # Positional a, should NOT cache
        assert len(calls_storage.storage) == 0
        assert "Missing required keyword arguments" in caplog.text

def test_combined_hints_and_args(memory_cache):
    calls_storage = memory_cache

    @fleche(ignore='a', require='d')
    def foo(a, b: Ignored, c: Required[Any] = None, d=None):
        return a

    # Missing d (from decorator) and a (from hint)
    foo(a=1, b=2, c=3)
    assert len(calls_storage.storage) == 0

    # All present as keyword args
    foo(a=1, b=2, c=3, d=4)
    assert len(calls_storage.storage) == 1
    key1 = foo.digest(a=1, b=2, c=3, d=4)

    # Change ignored b
    foo(a=1, b=5, c=3, d=4)
    assert len(calls_storage.storage) == 1
    # FIXME: how to get load count?
    # assert memory_cache.load_count >= 1
    key2 = foo.digest(a=1, b=5, c=3, d=4)

    assert key1 == key2

def test_ignored_not_in_call_arguments(memory_cache):
    calls_storage = memory_cache

    @fleche
    def foo(a, b: Ignored):
        return a

    foo(a=1, b=2)
    call = state._CACHE.get().load(foo.digest(a=1, b=2))
    assert 'a' in call.arguments
    assert 'b' not in call.arguments
