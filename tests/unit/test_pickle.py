"""Tests that all storages, caches, and their configurations are picklable.

Related issue: https://github.com/pmrv/fleche/issues/207
"""

import pickle
import pytest
from hypothesis import given, settings, HealthCheck

from fleche.storage import Memory, Void, PickleFile, DestructuringStorage
from fleche.caches import Cache, ReadOnlyCache, FilteredCache, RefreshingCache, CacheStack, Rejected
from tests.strategies import st_digested_calls


SECRET_KEY = [b"test_secret_key_32_bytes_long!!!!"]


def roundtrip(obj):
    """Pickle and unpickle an object, returning the restored copy."""
    return pickle.loads(pickle.dumps(obj))


# ---------------------------------------------------------------------------
# Storage picklability — parametrized via global fixtures
# ---------------------------------------------------------------------------


def test_value_storage_picklable(value_storage):
    """All value storage backends are picklable."""
    restored = roundtrip(value_storage)
    assert type(restored) == type(value_storage)


def test_call_storage_picklable(call_storage_adapter):
    """All call storage backends are picklable."""
    restored = roundtrip(call_storage_adapter)
    assert type(restored) == type(call_storage_adapter)


def test_void_picklable():
    assert isinstance(roundtrip(Void()), Void)


def test_destructuring_storage_picklable():
    ds = DestructuringStorage(Memory({}))
    restored = roundtrip(ds)
    assert isinstance(restored, DestructuringStorage)
    key = restored.save([1, 2, 3])
    assert restored.load(key) == [1, 2, 3]


# ---------------------------------------------------------------------------
# PickleFile-specific: attribute preservation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("compress", [False, True])
def test_pickle_file_attributes_preserved(tmp_path, compress):
    """PickleFile roundtrip preserves root, secret_key, and compress."""
    store = PickleFile.with_pickle(
        tmp_path / "store", secret_key=SECRET_KEY, compress=compress
    )
    key = store.save("hello")
    restored = roundtrip(store)
    assert restored.load(key) == "hello"
    assert restored.root == store.root
    assert restored.secret_key == store.secret_key
    assert restored.compress == store.compress


# ---------------------------------------------------------------------------
# Cache picklability — parametrized via value_storage + call_storage_adapter
# ---------------------------------------------------------------------------


def _always_true(call):
    return True


@pytest.fixture
def cache(value_storage, call_storage_adapter):
    return Cache(value_storage, call_storage_adapter)


def test_cache_picklable(cache):
    restored = roundtrip(cache)
    assert isinstance(restored, Cache)


def test_readonly_cache_picklable(cache):
    restored = roundtrip(ReadOnlyCache(cache))
    assert isinstance(restored, ReadOnlyCache)


def test_filtered_cache_picklable(cache):
    restored = roundtrip(FilteredCache(cache, _always_true))
    assert isinstance(restored, FilteredCache)


def test_refreshing_cache_picklable(cache):
    restored = roundtrip(RefreshingCache(cache))
    assert isinstance(restored, RefreshingCache)


def test_cache_stack_picklable(cache):
    stack = CacheStack((cache, Cache(Memory({}), Memory({}))))
    restored = roundtrip(stack)
    assert isinstance(restored, CacheStack)
    assert len(restored.stack) == 2


# ---------------------------------------------------------------------------
# Functional roundtrip: save → pickle → unpickle → load
# ---------------------------------------------------------------------------


@settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(call=st_digested_calls)
def test_call_storage_functional_roundtrip(call_storage_adapter, call):
    """Data saved to a call storage before pickling is accessible after restoring."""
    from fleche.storage import SaveError
    try:
        key = call_storage_adapter.save(call)
    except SaveError:
        return
    restored = roundtrip(call_storage_adapter)
    assert restored.load(key) == call


@settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(call=st_digested_calls)
def test_cache_functional_roundtrip(value_storage, call_storage_adapter, call):
    """Data saved to a cache before pickling is accessible after restoring."""
    cache = Cache(value_storage, call_storage_adapter)
    try:
        key = cache.save(call)
    except Rejected:
        return
    restored = roundtrip(cache)
    loaded = restored.load(key, lazy=False)
    assert loaded == call


@settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(call=st_digested_calls)
def test_cache_stack_functional_roundtrip(value_storage, call_storage_adapter, call):
    """CacheStack saves and loads correctly after pickling."""
    cache = Cache(value_storage, call_storage_adapter)
    try:
        key = cache.save(call)
    except Rejected:
        return
    stack = CacheStack((cache, Cache(Memory({}), Memory({}))))
    restored = roundtrip(stack)
    loaded = restored.load(key, lazy=False)
    assert loaded == call
