from fleche import storage
from fleche.caches import Cache, CachePool, CacheStack, ReadOnlyCache, SizeLimitedCache
from fleche.config import cache_from_config
import pytest


def test_cache_memory():
    cfg = {
        "values": {"type": "memory"},
        "calls": {"type": "memory"},
    }
    c = cache_from_config(cfg)
    assert isinstance(c, Cache)
    assert isinstance(c.values, storage.ValueMemory)
    assert isinstance(c.calls, storage.CallMemory)


def test_cache_void():
    cfg = {
        "values": {"type": "void"},
        "calls": {"type": "void"},
    }
    c = cache_from_config(cfg)
    assert isinstance(c, Cache)
    assert isinstance(c.values, storage.ValueVoid)
    assert isinstance(c.calls, storage.CallVoid)


def test_cache_does_not_mutate_input():
    cfg = {
        "values": {"type": "memory"},
        "calls": {"type": "memory"},
    }
    original = dict(cfg)
    cache_from_config(cfg)
    assert cfg == original


def test_size_limited_cache_does_not_mutate_input():
    cfg = {
        "values": {"type": "memory"},
        "calls": {"type": "memory"},
        "max_size": 10,
    }
    original = dict(cfg)
    cache_from_config(cfg)
    assert cfg == original


def test_size_limited_cache():
    """Presence of max_size implicitly creates a SizeLimitedCache."""
    cfg = {
        "values": {"type": "memory"},
        "calls": {"type": "memory"},
        "max_size": 10,
    }
    c = cache_from_config(cfg)
    assert isinstance(c, SizeLimitedCache)
    assert c.max_size == 10
    assert isinstance(c.values, storage.ValueMemory)
    assert isinstance(c.calls, storage.CallMemory)


def test_readonly_cache():
    """read_only: True implicitly wraps the cache in ReadOnlyCache."""
    cfg = {
        "values": {"type": "memory"},
        "calls": {"type": "memory"},
        "read_only": True,
    }
    c = cache_from_config(cfg)
    assert isinstance(c, ReadOnlyCache)
    assert isinstance(c.cache, Cache)


def test_readonly_size_limited_cache():
    """read_only and max_size can be combined."""
    cfg = {
        "values": {"type": "memory"},
        "calls": {"type": "memory"},
        "max_size": 5,
        "read_only": True,
    }
    c = cache_from_config(cfg)
    assert isinstance(c, ReadOnlyCache)
    assert isinstance(c.cache, SizeLimitedCache)
    assert c.cache.max_size == 5


def test_cache_stack_from_list():
    """A list of dicts is implicitly treated as a CacheStack."""
    cfg = [
        {"values": {"type": "memory"}, "calls": {"type": "memory"}},
        {"values": {"type": "void"}, "calls": {"type": "void"}},
    ]
    c = cache_from_config(cfg)
    assert isinstance(c, CacheStack)
    assert len(c.stack) == 2
    assert isinstance(c.stack[0], Cache)
    assert isinstance(c.stack[1], Cache)


def test_cache_stack_nested_readonly():
    """CacheStack from list with a read_only element."""
    cfg = [
        {
            "values": {"type": "memory"},
            "calls": {"type": "memory"},
            "read_only": True,
        },
        {"values": {"type": "void"}, "calls": {"type": "void"}},
    ]
    c = cache_from_config(cfg)
    assert isinstance(c, CacheStack)
    assert isinstance(c.stack[0], ReadOnlyCache)
    assert isinstance(c.stack[1], Cache)


def test_cache_pool_from_dict():
    """A dict with a `pool` key is implicitly treated as a CachePool."""
    cfg = {
        "pool": [
            {"values": {"type": "memory"}, "calls": {"type": "memory"}},
            {"values": {"type": "void"}, "calls": {"type": "void"}},
        ]
    }
    c = cache_from_config(cfg)
    assert isinstance(c, CachePool)
    assert len(c.caches) == 2
    assert isinstance(c.caches[0], Cache)
    assert isinstance(c.caches[0].values, storage.ValueMemory)
    assert isinstance(c.caches[1].values, storage.ValueVoid)


def test_cache_pool_nested_members():
    """Pool members are processed recursively (e.g. read-only / stack)."""
    cfg = {
        "pool": [
            {
                "values": {"type": "memory"},
                "calls": {"type": "memory"},
                "read_only": True,
            },
            [
                {"values": {"type": "memory"}, "calls": {"type": "memory"}},
                {"values": {"type": "void"}, "calls": {"type": "void"}},
            ],
        ]
    }
    c = cache_from_config(cfg)
    assert isinstance(c, CachePool)
    assert isinstance(c.caches[0], ReadOnlyCache)
    assert isinstance(c.caches[1], CacheStack)


def test_cache_pickle_file(tmp_path):
    cfg = {
        "values": {"type": "pickle", "root": str(tmp_path / "values")},
        "calls": {"type": "pickle", "root": str(tmp_path / "calls")},
    }
    c = cache_from_config(cfg)
    assert isinstance(c, Cache)
    assert isinstance(c.values, storage.ValuePickleFile)
    assert isinstance(c.calls, storage.CallPickleFile)


def test_cache_sql(tmp_path):
    pytest.importorskip("sqlalchemy")
    url = f"sqlite:///{tmp_path / 'calls.db'}"
    cfg = {
        "values": {"type": "memory"},
        "calls": {"type": "sql", "url": url},
    }
    c = cache_from_config(cfg)
    assert isinstance(c, Cache)
    assert isinstance(c.calls, storage.Sql)
    assert c.calls.url == url
