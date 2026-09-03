"""Tests that all storages, caches, their configurations, and decorated functions are picklable.

Related issues:
- https://github.com/pmrv/fleche/issues/207
- https://github.com/pmrv/fleche/issues/172
"""

import pickle
import pytest
from hypothesis import given, settings, HealthCheck

from fleche import fleche
from fleche.storage import ValueMemory, CallMemory, ValueVoid, ValuePickleFile
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
    assert type(restored) is type(value_storage)


def test_call_storage_picklable(call_storage):
    """All call storage backends are picklable."""
    restored = roundtrip(call_storage)
    assert type(restored) is type(call_storage)


def test_void_picklable():
    assert isinstance(roundtrip(ValueVoid()), ValueVoid)



# ---------------------------------------------------------------------------
# PickleFile-specific: attribute preservation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("compress", [False, True])
def test_pickle_file_attributes_preserved(tmp_path, compress):
    """PickleFile roundtrip preserves root, secret_key, and compress."""
    store = ValuePickleFile.with_pickle(
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
def cache(paired_storages):
    # A Cache is a frozen dataclass over two independent halves, and each half's
    # own picklability across every backend is swept by
    # test_value_storage_picklable / test_call_storage_picklable.  So a cache
    # needs one case per backend, not one per pair of them: `paired_storages`
    # rather than `value_storage, call_storage`.
    return Cache(*paired_storages)


def test_cache_picklable(cache):
    restored = roundtrip(cache)
    assert isinstance(restored, Cache)


# Wrapper picklability is backend-independent; test_cache_picklable sweeps backends.
def _inner():
    return Cache(ValueMemory({}), CallMemory({}))


def test_readonly_cache_picklable():
    restored = roundtrip(ReadOnlyCache(_inner()))
    assert isinstance(restored, ReadOnlyCache)


def test_filtered_cache_picklable():
    restored = roundtrip(FilteredCache(_inner(), _always_true))
    assert isinstance(restored, FilteredCache)


def test_refreshing_cache_picklable():
    restored = roundtrip(RefreshingCache(_inner()))
    assert isinstance(restored, RefreshingCache)


def test_cache_stack_picklable():
    stack = CacheStack((_inner(), _inner()))
    restored = roundtrip(stack)
    assert isinstance(restored, CacheStack)
    assert len(restored.stack) == 2


def test_size_limited_cache_picklable():
    """SizeLimitedCache roundtrips through pickle and remains functional."""
    from fleche.caches import SizeLimitedCache
    from fleche.call import Call
    cache = SizeLimitedCache(ValueMemory({}), CallMemory({}), max_size=5)
    call_obj = Call(name="f", arguments={"x": 1}, result=2, module="test", version=1, metadata={})
    key = cache.save(call_obj)
    restored = roundtrip(cache)
    assert isinstance(restored, SizeLimitedCache)
    assert restored.contains(key)


# ---------------------------------------------------------------------------
# Functional roundtrip: save → pickle → unpickle → load
# ---------------------------------------------------------------------------


@settings(suppress_health_check=[HealthCheck.function_scoped_fixture], deadline=None)
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


@settings(suppress_health_check=[HealthCheck.function_scoped_fixture], deadline=None)
@given(call=st_digested_calls)
def test_cache_functional_roundtrip(paired_storages, call):
    """Data saved to a cache before pickling is accessible after restoring."""
    cache = Cache(*paired_storages)
    try:
        key = cache.save(call)
    except Rejected:
        return
    restored = roundtrip(cache)
    loaded = restored.load(key).fetch()
    assert loaded == call


@settings(deadline=None)
@given(call=st_digested_calls)
def test_cache_stack_functional_roundtrip(call):
    """A pickled CacheStack still resolves a key held by one of its layers.

    Single-backend by design: a stack holds caches, not storages, and treats
    them identically, so what is unique here is CacheStack's own delegation
    surviving the roundtrip.  Sweeping the backends is
    test_cache_functional_roundtrip's job.
    """
    cache = Cache(ValueMemory({}), CallMemory({}))
    key = cache.save(call)
    stack = CacheStack((cache, Cache(ValueMemory({}), CallMemory({}))))
    restored = roundtrip(stack)
    loaded = restored.load(key).fetch()
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
