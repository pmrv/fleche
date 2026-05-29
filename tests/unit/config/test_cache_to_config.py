import pytest

from fleche import storage
from fleche.caches import BaseCache, Cache, CacheStack, ReadOnlyCache, SizeLimitedCache
from fleche.config import cache_from_config, cache_to_config


# ─── cache_to_config unit tests ───────────────────────────────────────────────


def test_cache_to_config_memory():
    c = Cache(values=storage.ValueMemory({}), calls=storage.CallMemory({}))
    cfg = cache_to_config(c)
    assert cfg == {
        "values": {"type": "memory", "remaining_depth": 0},
        "calls": {"type": "memory"},
    }


def test_cache_to_config_void():
    c = Cache(values=storage.ValueVoid(), calls=storage.CallVoid())
    cfg = cache_to_config(c)
    assert cfg == {
        "values": {"type": "void"},
        "calls": {"type": "void"},
    }


def test_cache_to_config_size_limited():
    c = SizeLimitedCache(
        values=storage.ValueMemory({}),
        calls=storage.CallMemory({}),
        max_size=5,
    )
    cfg = cache_to_config(c)
    assert cfg == {
        "values": {"type": "memory", "remaining_depth": 0},
        "calls": {"type": "memory"},
        "max_size": 5,
    }


def test_cache_to_config_readonly():
    inner = Cache(values=storage.ValueMemory({}), calls=storage.CallMemory({}))
    c = ReadOnlyCache(inner)
    cfg = cache_to_config(c)
    assert cfg == {
            "values": {"type": "memory", "remaining_depth": 0},
            "calls": {"type": "memory"},
            "read_only": True,
    }


def test_cache_to_config_readonly_size_limited():
    inner = SizeLimitedCache(
        values=storage.ValueMemory({}),
        calls=storage.CallMemory({}),
        max_size=7,
    )
    c = ReadOnlyCache(inner)
    cfg = cache_to_config(c)
    assert cfg == {
        "values": {"type": "memory", "remaining_depth": 0},
        "calls": {"type": "memory"},
        "max_size": 7,
        "read_only": True,
    }


def test_cache_to_config_cache_stack():
    c = CacheStack((
        Cache(values=storage.ValueMemory({}), calls=storage.CallMemory({})),
        Cache(values=storage.ValueVoid(), calls=storage.CallVoid()),
    ))
    cfg = cache_to_config(c)
    assert isinstance(cfg, list)
    assert len(cfg) == 2
    assert cfg[0]["values"]["type"] == "memory"
    assert cfg[1]["values"]["type"] == "void"


def test_cache_to_config_readonly_wrapping_stack_raises():
    inner = CacheStack((
        Cache(values=storage.ValueMemory({}), calls=storage.CallMemory({})),
    ))
    c = ReadOnlyCache(inner)
    with pytest.raises(ValueError, match="CacheStack"):
        cache_to_config(c)


def test_cache_to_config_unknown_raises():
    class UnknownCache(BaseCache):
        def save(self, call):
            return ""

        def load(self, key):
            raise KeyError(key)

        def load_value(self, key):
            raise KeyError(key)

        def evict(self, key):
            pass

        def contains(self, key):
            return False

        def expand(self, key):
            raise KeyError(key)

        def _shrink(self, *keys):
            raise KeyError(keys[0])

        def _query(self, call):
            return iter([])

    with pytest.raises(ValueError, match="UnknownCache"):
        cache_to_config(UnknownCache())


def test_cache_to_config_pickle_file(tmp_path):
    c = Cache(
        values=storage.ValuePickleFile.with_pickle(root=tmp_path / "values"),
        calls=storage.CallPickleFile.with_pickle(root=tmp_path / "calls"),
    )
    cfg = cache_to_config(c)
    assert cfg["values"]["type"] == "pickle"
    assert cfg["calls"]["type"] == "pickle"
    assert cfg["values"]["root"] == str(tmp_path / "values")
    assert cfg["calls"]["root"] == str(tmp_path / "calls")


def test_cache_to_config_sql(tmp_path):
    pytest.importorskip("sqlalchemy")
    url = f"sqlite:///{tmp_path / 'calls.db'}"
    c = Cache(
        values=storage.ValueMemory({}),
        calls=storage.Sql(url=url),
    )
    cfg = cache_to_config(c)
    assert cfg["calls"]["type"] == "sql"
    assert cfg["calls"]["url"] == url


# ─── roundtrip tests ──────────────────────────────────────────────────────────


def test_roundtrip_memory():
    original = Cache(values=storage.ValueMemory({}), calls=storage.CallMemory({}))
    reconstructed = cache_from_config(cache_to_config(original))
    assert isinstance(reconstructed, Cache)
    assert isinstance(reconstructed.values, storage.ValueMemory)
    assert isinstance(reconstructed.calls, storage.CallMemory)


def test_roundtrip_void():
    original = Cache(values=storage.ValueVoid(), calls=storage.CallVoid())
    reconstructed = cache_from_config(cache_to_config(original))
    assert isinstance(reconstructed, Cache)
    assert isinstance(reconstructed.values, storage.ValueVoid)
    assert isinstance(reconstructed.calls, storage.CallVoid)


def test_roundtrip_size_limited():
    original = SizeLimitedCache(
        values=storage.ValueMemory({}),
        calls=storage.CallMemory({}),
        max_size=42,
    )
    reconstructed = cache_from_config(cache_to_config(original))
    assert isinstance(reconstructed, SizeLimitedCache)
    assert reconstructed.max_size == 42
    assert isinstance(reconstructed.values, storage.ValueMemory)
    assert isinstance(reconstructed.calls, storage.CallMemory)


def test_roundtrip_readonly():
    inner = Cache(values=storage.ValueMemory({}), calls=storage.CallMemory({}))
    original = ReadOnlyCache(inner)
    reconstructed = cache_from_config(cache_to_config(original))
    assert isinstance(reconstructed, ReadOnlyCache)
    assert isinstance(reconstructed.cache, Cache)
    assert isinstance(reconstructed.cache.values, storage.ValueMemory)


def test_roundtrip_readonly_size_limited():
    inner = SizeLimitedCache(
        values=storage.ValueMemory({}),
        calls=storage.CallMemory({}),
        max_size=10,
    )
    original = ReadOnlyCache(inner)
    reconstructed = cache_from_config(cache_to_config(original))
    assert isinstance(reconstructed, ReadOnlyCache)
    assert isinstance(reconstructed.cache, SizeLimitedCache)
    assert reconstructed.cache.max_size == 10


def test_roundtrip_cache_stack():
    original = CacheStack((
        Cache(values=storage.ValueMemory({}), calls=storage.CallMemory({})),
        Cache(values=storage.ValueVoid(), calls=storage.CallVoid()),
    ))
    reconstructed = cache_from_config(cache_to_config(original))
    assert isinstance(reconstructed, CacheStack)
    assert len(reconstructed.stack) == 2
    assert isinstance(reconstructed.stack[0].values, storage.ValueMemory)
    assert isinstance(reconstructed.stack[1].values, storage.ValueVoid)


def test_roundtrip_pickle_file(tmp_path):
    original = Cache(
        values=storage.ValuePickleFile.with_pickle(root=tmp_path / "values"),
        calls=storage.CallPickleFile.with_pickle(root=tmp_path / "calls"),
    )
    reconstructed = cache_from_config(cache_to_config(original))
    assert isinstance(reconstructed, Cache)
    assert isinstance(reconstructed.values, storage.ValuePickleFile)
    assert reconstructed.values.root == original.values.root
    assert isinstance(reconstructed.calls, storage.CallPickleFile)
    assert reconstructed.calls.root == original.calls.root


def test_roundtrip_sql(tmp_path):
    pytest.importorskip("sqlalchemy")
    url = f"sqlite:///{tmp_path / 'calls.db'}"
    original = Cache(
        values=storage.ValueMemory({}),
        calls=storage.Sql(url=url),
    )
    reconstructed = cache_from_config(cache_to_config(original))
    assert isinstance(reconstructed, Cache)
    assert isinstance(reconstructed.calls, storage.Sql)
    assert reconstructed.calls.url == url


def test_roundtrip_cache_stack_nested_readonly():
    stack = CacheStack((
        ReadOnlyCache(
            Cache(
                values=storage.ValueMemory({}),
                calls=storage.CallMemory({}),
            )
        ),
        Cache(
            values=storage.ValueVoid(),
            calls=storage.CallVoid(),
        ),
    ))
    reconstructed = cache_from_config(cache_to_config(stack))
    assert isinstance(reconstructed, CacheStack)
    assert isinstance(reconstructed.stack[0], ReadOnlyCache)
    assert isinstance(reconstructed.stack[0].cache, Cache)
    assert isinstance(reconstructed.stack[1], Cache)
