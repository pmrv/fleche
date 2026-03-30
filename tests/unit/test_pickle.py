"""Tests that all storages, caches, their configurations, and decorated functions are picklable.

Related issues:
- https://github.com/pmrv/fleche/issues/207
- https://github.com/pmrv/fleche/issues/172
"""

import pickle
import pytest
from hypothesis import given, settings, HealthCheck

from fleche import fleche
from fleche.storage import Memory, Void, PickleFile, DestructuringStorage
from fleche.storage.sql import Sql
from fleche.caches import Cache, ReadOnlyCache, FilteredCache, RefreshingCache, CacheStack, Rejected
from tests.strategies import st_digested_calls


# Module-level decorated function — must be at module level to be picklable
@fleche
def _example(x, y):
    return x + y


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


def test_call_storage_picklable(call_storage):
    """All call storage backends are picklable."""
    restored = roundtrip(call_storage)
    assert type(restored) == type(call_storage)


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
# Cache picklability — parametrized via value_storage + call_storage
# ---------------------------------------------------------------------------


def _always_true(call):
    return True


@pytest.fixture
def cache(value_storage, call_storage):
    return Cache(value_storage, call_storage)


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
def test_call_storage_functional_roundtrip(call_storage, call):
    """Data saved to a call storage before pickling is accessible after restoring."""
    from fleche.storage import SaveError
    try:
        key = call_storage.save(call)
    except SaveError:
        return
    restored = roundtrip(call_storage)
    assert restored.load(key) == call


@settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(call=st_digested_calls)
def test_cache_functional_roundtrip(value_storage, call_storage, call):
    """Data saved to a cache before pickling is accessible after restoring."""
    cache = Cache(value_storage, call_storage)
    try:
        key = cache.save(call)
    except Rejected:
        return
    restored = roundtrip(cache)
    loaded = restored.load(key, lazy=False)
    assert loaded == call


@settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(call=st_digested_calls)
def test_cache_stack_functional_roundtrip(value_storage, call_storage, call):
    """CacheStack saves and loads correctly after pickling."""
    cache = Cache(value_storage, call_storage)
    try:
        key = cache.save(call)
    except Rejected:
        return
    stack = CacheStack((cache, Cache(Memory({}), Memory({}))))
    restored = roundtrip(stack)
    loaded = restored.load(key, lazy=False)
    assert loaded == call


# ---------------------------------------------------------------------------
# SQL backend picklability
# ---------------------------------------------------------------------------


def test_sql_picklable():
    """Sql storage backend roundtrips through pickle correctly."""
    sql = Sql("sqlite:///:memory:")
    restored = roundtrip(sql)
    assert sql == restored


# ---------------------------------------------------------------------------
# Decorated function and helper picklability
# ---------------------------------------------------------------------------


def test_pickle_decorated_function():
    pickled = pickle.dumps(_example)
    recovered = pickle.loads(pickled)
    assert recovered is _example


def test_pickle_call_helper():
    pickled = pickle.dumps(_example.call)
    recovered = pickle.loads(pickled)
    assert recovered is _example.call


def test_pickle_digest_helper():
    pickled = pickle.dumps(_example.digest)
    recovered = pickle.loads(pickled)
    assert recovered is _example.digest


def test_pickle_contains_helper():
    pickled = pickle.dumps(_example.contains)
    recovered = pickle.loads(pickled)
    assert recovered is _example.contains


def test_pickle_load_helper():
    pickled = pickle.dumps(_example.load)
    recovered = pickle.loads(pickled)
    assert recovered is _example.load


def test_pickle_rerun_helper():
    pickled = pickle.dumps(_example.rerun)
    recovered = pickle.loads(pickled)
    assert recovered is _example.rerun
