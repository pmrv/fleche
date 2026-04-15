"""Regression tests for issue #297: Required args supplied positionally were not recognised."""
import logging
import pytest
from fleche.storage import memory
from fleche.caches import Cache
from fleche import fleche, Required
import fleche.state as state


@pytest.fixture
def memory_cache():
    values_storage = memory.ValueMemory(storage={})
    calls_storage = memory.CallMemory(storage={})
    cache = Cache(values=values_storage, calls=calls_storage)
    token = state._CACHE.set(cache)
    yield calls_storage
    state._CACHE.reset(token)


def test_required_default_positional_caches(memory_cache, caplog):
    """Required arg with a default, when passed positionally, should cache (#297)."""
    calls_storage = memory_cache

    @fleche(require='seed')
    def foo(base, seed=None):
        return base + (seed or 0)

    # seed not provided (uses default None) — should NOT cache
    caplog.clear()
    with caplog.at_level(logging.WARNING):
        foo(1)
        assert len(calls_storage.storage) == 0
        assert "Missing required keyword arguments" in caplog.text

    # seed provided positionally — should cache
    caplog.clear()
    with caplog.at_level(logging.WARNING):
        foo(1, 42)
        assert len(calls_storage.storage) == 1
        assert "Missing required keyword arguments" not in caplog.text

    # seed provided as keyword — should also cache
    caplog.clear()
    with caplog.at_level(logging.WARNING):
        foo(1, seed=99)
        assert len(calls_storage.storage) == 2
        assert "Missing required keyword arguments" not in caplog.text
