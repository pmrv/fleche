import pytest

from fleche import storage
from fleche.caches import Cache, CacheStack, ReadOnlyCache, SizeLimitedCache
from fleche.config import cache_from_config


def test_cache_memory():
    cfg = {
        "type": "Cache",
        "values": {"type": "Memory"},
        "calls": {"type": "Memory"},
    }
    c = cache_from_config(cfg)
    assert isinstance(c, Cache)
    assert isinstance(c.values, storage.DestructuringStorage)
    assert isinstance(c.values.storage, storage.Memory)
    assert isinstance(c.calls.storage, storage.Memory)


def test_cache_default_type():
    """type defaults to "Cache" when absent."""
    cfg = {
        "values": {"type": "Memory"},
        "calls": {"type": "Memory"},
    }
    c = cache_from_config(cfg)
    assert isinstance(c, Cache)


def test_cache_does_not_mutate_input():
    cfg = {
        "type": "Cache",
        "values": {"type": "Memory"},
        "calls": {"type": "Memory"},
    }
    original = dict(cfg)
    cache_from_config(cfg)
    assert cfg == original


def test_cache_wraps_values_in_destructuring_storage():
    """values without DestructuringStorage in config gets wrapped automatically."""
    cfg = {
        "type": "Cache",
        "values": {"type": "Memory"},
        "calls": {"type": "Memory"},
    }
    c = cache_from_config(cfg)
    assert isinstance(c.values, storage.DestructuringStorage)


def test_cache_with_explicit_destructuring_storage():
    """If values is already a DestructuringStorage dict, it is not double-wrapped."""
    cfg = {
        "type": "Cache",
        "values": {"type": "DestructuringStorage", "storage": {"type": "Memory"}},
        "calls": {"type": "Memory"},
    }
    c = cache_from_config(cfg)
    assert isinstance(c.values, storage.DestructuringStorage)
    assert isinstance(c.values.storage, storage.Memory)
    # Verify no double-wrapping
    assert not isinstance(c.values.storage, storage.DestructuringStorage)


def test_cache_void():
    cfg = {
        "type": "Cache",
        "values": {"type": "Void"},
        "calls": {"type": "Void"},
    }
    c = cache_from_config(cfg)
    assert isinstance(c, Cache)
    assert isinstance(c.values.storage, storage.Void)
    assert isinstance(c.calls.storage, storage.Void)


def test_size_limited_cache():
    cfg = {
        "type": "SizeLimitedCache",
        "values": {"type": "Memory"},
        "calls": {"type": "Memory"},
        "max_size": 10,
    }
    c = cache_from_config(cfg)
    assert isinstance(c, SizeLimitedCache)
    assert c.max_size == 10
    assert isinstance(c.values, storage.DestructuringStorage)
    assert isinstance(c.values.storage, storage.Memory)
    assert isinstance(c.calls.storage, storage.Memory)


def test_readonly_cache():
    cfg = {
        "type": "ReadOnlyCache",
        "cache": {
            "type": "Cache",
            "values": {"type": "Memory"},
            "calls": {"type": "Memory"},
        },
    }
    c = cache_from_config(cfg)
    assert isinstance(c, ReadOnlyCache)
    assert isinstance(c.cache, Cache)


def test_cache_stack():
    cfg = {
        "type": "CacheStack",
        "stack": [
            {"type": "Cache", "values": {"type": "Memory"}, "calls": {"type": "Memory"}},
            {"type": "Cache", "values": {"type": "Void"}, "calls": {"type": "Void"}},
        ],
    }
    c = cache_from_config(cfg)
    assert isinstance(c, CacheStack)
    assert len(c.stack) == 2
    assert isinstance(c.stack[0], Cache)
    assert isinstance(c.stack[1], Cache)


def test_cache_stack_nested_readonly():
    cfg = {
        "type": "CacheStack",
        "stack": [
            {
                "type": "ReadOnlyCache",
                "cache": {"type": "Cache", "values": {"type": "Memory"}, "calls": {"type": "Memory"}},
            },
            {"type": "Cache", "values": {"type": "Void"}, "calls": {"type": "Void"}},
        ],
    }
    c = cache_from_config(cfg)
    assert isinstance(c, CacheStack)
    assert isinstance(c.stack[0], ReadOnlyCache)
    assert isinstance(c.stack[1], Cache)


def test_unknown_cache_type_raises():
    cfg = {"type": "NonExistentCache", "values": {"type": "Memory"}, "calls": {"type": "Memory"}}
    with pytest.raises(ValueError, match="NonExistentCache"):
        cache_from_config(cfg)


def test_cache_pickle_file(tmp_path):
    cfg = {
        "type": "Cache",
        "values": {"type": "PickleFile", "root": str(tmp_path / "values")},
        "calls": {"type": "PickleFile", "root": str(tmp_path / "calls")},
    }
    c = cache_from_config(cfg)
    assert isinstance(c, Cache)
    assert isinstance(c.values, storage.DestructuringStorage)
    assert isinstance(c.values.storage, storage.PickleFile)
    assert isinstance(c.calls.storage, storage.PickleFile)
