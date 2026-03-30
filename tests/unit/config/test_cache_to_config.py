import pytest

from fleche import storage
from fleche.caches import BaseCache, Cache, CacheStack, ReadOnlyCache, SizeLimitedCache
from fleche.config import cache_from_config, cache_to_config


# ─── cache_to_config unit tests ───────────────────────────────────────────────


def test_cache_to_config_memory():
    c = Cache(
        values=storage.DestructuringStorage(storage.Memory({})),
        _calls=storage.Memory({}),
    )
    cfg = cache_to_config(c)
    assert cfg == {
        "values": {"type": "DestructuringStorage", "storage": {"type": "Memory"}},
        "calls": {"type": "Memory"},
    }


def test_cache_to_config_size_limited():
    c = SizeLimitedCache(
        values=storage.DestructuringStorage(storage.Memory({})),
        _calls=storage.Memory({}),
        max_size=5,
    )
    cfg = cache_to_config(c)
    assert cfg == {
        "values": {"type": "DestructuringStorage", "storage": {"type": "Memory"}},
        "calls": {"type": "Memory"},
        "max_size": 5,
    }


def test_cache_to_config_readonly():
    inner = Cache(
        values=storage.DestructuringStorage(storage.Memory({})),
        _calls=storage.Memory({}),
    )
    c = ReadOnlyCache(inner)
    cfg = cache_to_config(c)
    assert cfg == {
        "values": {"type": "DestructuringStorage", "storage": {"type": "Memory"}},
        "calls": {"type": "Memory"},
        "read_only": True,
    }


def test_cache_to_config_readonly_size_limited():
    inner = SizeLimitedCache(
        values=storage.DestructuringStorage(storage.Memory({})),
        _calls=storage.Memory({}),
        max_size=7,
    )
    c = ReadOnlyCache(inner)
    cfg = cache_to_config(c)
    assert cfg == {
        "values": {"type": "DestructuringStorage", "storage": {"type": "Memory"}},
        "calls": {"type": "Memory"},
        "max_size": 7,
        "read_only": True,
    }


def test_cache_to_config_cache_stack():
    c = CacheStack((
        Cache(values=storage.DestructuringStorage(storage.Memory({})), _calls=storage.Memory({})),
        Cache(values=storage.DestructuringStorage(storage.Void()), _calls=storage.Void()),
    ))
    cfg = cache_to_config(c)
    assert isinstance(cfg, list)
    assert len(cfg) == 2
    assert cfg[0]["values"]["storage"]["type"] == "Memory"
    assert cfg[1]["values"]["storage"]["type"] == "Void"


def test_cache_to_config_readonly_wrapping_stack_raises():
    inner = CacheStack((
        Cache(values=storage.DestructuringStorage(storage.Memory({})), _calls=storage.Memory({})),
    ))
    c = ReadOnlyCache(inner)
    with pytest.raises(ValueError, match="CacheStack"):
        cache_to_config(c)


def test_cache_to_config_unknown_raises():
    class UnknownCache(BaseCache):
        def save(self, call):
            return ""

        def load(self, key, lazy=True):
            raise KeyError(key)

        def load_value(self, key):
            raise KeyError(key)

        def evict(self, key):
            pass

        def contains(self, key):
            return False

        def expand(self, key):
            raise KeyError(key)

        def shrink(self, key):
            raise KeyError(key)

        def _query(self, call):
            return iter([])

    with pytest.raises(ValueError, match="UnknownCache"):
        cache_to_config(UnknownCache())


# ─── roundtrip tests ──────────────────────────────────────────────────────────


def _assert_storage_equivalent(a: storage.Storage, b: storage.Storage) -> None:
    """Check that two storage instances have the same type and root/url."""
    assert type(a) is type(b)
    if hasattr(a, "root"):
        assert a.root == b.root
    if hasattr(a, "url"):
        assert a.url == b.url


def _assert_cache_equivalent(a: BaseCache, b: BaseCache) -> None:
    """Recursively verify that two caches have the same structure and config."""
    assert type(a) is type(b), f"Cache types differ: {type(a).__name__} vs {type(b).__name__}"
    if isinstance(a, CacheStack):
        assert isinstance(b, CacheStack)
        assert len(a.stack) == len(b.stack)
        for ca, cb in zip(a.stack, b.stack):
            _assert_cache_equivalent(ca, cb)
    elif isinstance(a, ReadOnlyCache):
        assert isinstance(b, ReadOnlyCache)
        _assert_cache_equivalent(a.cache, b.cache)
    elif isinstance(a, SizeLimitedCache):
        assert isinstance(b, SizeLimitedCache)
        assert a.max_size == b.max_size
        _assert_storage_equivalent(a.values, b.values)
        _assert_storage_equivalent(a.calls.storage, b.calls.storage)
    elif isinstance(a, Cache):
        _assert_storage_equivalent(a.values, b.values)
        _assert_storage_equivalent(a.calls.storage, b.calls.storage)


def test_roundtrip_cache_memory():
    original = Cache(
        values=storage.DestructuringStorage(storage.Memory({})),
        _calls=storage.Memory({}),
    )
    reconstructed = cache_from_config(cache_to_config(original))
    assert isinstance(reconstructed, Cache)
    assert isinstance(reconstructed.values, storage.DestructuringStorage)
    assert isinstance(reconstructed.values.storage, storage.Memory)
    assert isinstance(reconstructed.calls.storage, storage.Memory)


def test_roundtrip_cache_void():
    original = Cache(
        values=storage.DestructuringStorage(storage.Void()),
        _calls=storage.Void(),
    )
    reconstructed = cache_from_config(cache_to_config(original))
    assert isinstance(reconstructed, Cache)
    assert isinstance(reconstructed.values.storage, storage.Void)
    assert isinstance(reconstructed.calls.storage, storage.Void)


def test_roundtrip_size_limited_cache():
    original = SizeLimitedCache(
        values=storage.DestructuringStorage(storage.Memory({})),
        _calls=storage.Memory({}),
        max_size=42,
    )
    reconstructed = cache_from_config(cache_to_config(original))
    assert isinstance(reconstructed, SizeLimitedCache)
    assert reconstructed.max_size == 42
    assert isinstance(reconstructed.values.storage, storage.Memory)
    assert isinstance(reconstructed.calls.storage, storage.Memory)


def test_roundtrip_readonly_cache():
    inner = Cache(
        values=storage.DestructuringStorage(storage.Memory({})),
        _calls=storage.Memory({}),
    )
    original = ReadOnlyCache(inner)
    reconstructed = cache_from_config(cache_to_config(original))
    assert isinstance(reconstructed, ReadOnlyCache)
    assert isinstance(reconstructed.cache, Cache)
    assert isinstance(reconstructed.cache.values.storage, storage.Memory)


def test_roundtrip_readonly_size_limited_cache():
    inner = SizeLimitedCache(
        values=storage.DestructuringStorage(storage.Memory({})),
        _calls=storage.Memory({}),
        max_size=10,
    )
    original = ReadOnlyCache(inner)
    reconstructed = cache_from_config(cache_to_config(original))
    assert isinstance(reconstructed, ReadOnlyCache)
    assert isinstance(reconstructed.cache, SizeLimitedCache)
    assert reconstructed.cache.max_size == 10


def test_roundtrip_cache_stack():
    original = CacheStack((
        Cache(values=storage.DestructuringStorage(storage.Memory({})), _calls=storage.Memory({})),
        Cache(values=storage.DestructuringStorage(storage.Void()), _calls=storage.Void()),
    ))
    reconstructed = cache_from_config(cache_to_config(original))
    assert isinstance(reconstructed, CacheStack)
    assert len(reconstructed.stack) == 2
    assert isinstance(reconstructed.stack[0].values.storage, storage.Memory)
    assert isinstance(reconstructed.stack[1].values.storage, storage.Void)


def test_roundtrip_cache_pickle_file(tmp_path):
    original = Cache(
        values=storage.DestructuringStorage(
            storage.PickleFile.with_pickle(root=tmp_path / "values")
        ),
        _calls=storage.PickleFile.with_pickle(root=tmp_path / "calls"),
    )
    reconstructed = cache_from_config(cache_to_config(original))
    assert isinstance(reconstructed, Cache)
    assert isinstance(reconstructed.values.storage, storage.PickleFile)
    assert reconstructed.values.storage.root == original.values.storage.root
    assert isinstance(reconstructed.calls.storage, storage.PickleFile)
    assert reconstructed.calls.storage.root == original.calls.storage.root


def test_roundtrip_cache_sql(tmp_path):
    pytest.importorskip("sqlalchemy")
    url = f"sqlite:///{tmp_path / 'calls.db'}"
    original = Cache(
        values=storage.DestructuringStorage(storage.Memory({})),
        _calls=storage.Sql(url=url),
    )
    reconstructed = cache_from_config(cache_to_config(original))
    assert isinstance(reconstructed, Cache)
    # Sql is a CallStorage subclass, so __post_init__ leaves it unwrapped
    calls = reconstructed.calls
    calls_storage = calls.storage if isinstance(calls, storage.CallStorageAdapter) else calls
    assert isinstance(calls_storage, storage.Sql)
    assert calls_storage.url == url


def test_roundtrip_cache_stack_nested_readonly():
    stack = CacheStack((
        ReadOnlyCache(
            Cache(
                values=storage.DestructuringStorage(storage.Memory({})),
                _calls=storage.Memory({}),
            )
        ),
        Cache(
            values=storage.DestructuringStorage(storage.Void()),
            _calls=storage.Void(),
        ),
    ))
    reconstructed = cache_from_config(cache_to_config(stack))
    assert isinstance(reconstructed, CacheStack)
    assert isinstance(reconstructed.stack[0], ReadOnlyCache)
    assert isinstance(reconstructed.stack[0].cache, Cache)
    assert isinstance(reconstructed.stack[1], Cache)
