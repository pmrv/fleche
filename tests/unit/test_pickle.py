"""Tests that all storages, caches, their configurations, and decorated functions are picklable.

Related issues:
- https://github.com/pmrv/fleche/issues/207
- https://github.com/pmrv/fleche/issues/172
"""

import pickle
import pytest
from hypothesis import given, settings, HealthCheck

from fleche import fleche
from fleche.call import Call
from fleche.storage import ValueMemory, CallMemory, ValueVoid, ValuePickleFile, CallPickleFile
from fleche.storage import ValueBagOfHoldingH5File, CallBagOfHoldingH5File
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
    stack = CacheStack((cache, Cache(ValueMemory({}), CallMemory({}))))
    restored = roundtrip(stack)
    assert isinstance(restored, CacheStack)
    assert len(restored.stack) == 2


# ---------------------------------------------------------------------------
# Fast fixtures for Hypothesis-based functional roundtrip tests
#
# HDF5 and SQL backends are excluded here because H5Bag's file-open/write/close
# cycle per Hypothesis trial (~20-50 ms each) makes the 100-example default
# unacceptably slow (≈ 80 s for all h5 variants combined).  Those backends are
# covered by dedicated fixed-example tests below.
# ---------------------------------------------------------------------------


@pytest.fixture(params=["memory", "cloudpickle", "dill", "pickle"])
def fast_value_storage(request, tmp_path):
    """Value storage backends for Hypothesis tests (HDF5 excluded)."""
    if request.param == "memory":
        return ValueMemory({})
    elif request.param == "cloudpickle":
        return ValuePickleFile.with_cloudpickle(tmp_path / "cloudpickle", secret_key=SECRET_KEY)
    elif request.param == "dill":
        return ValuePickleFile.with_dill(tmp_path / "dill", secret_key=SECRET_KEY)
    elif request.param == "pickle":
        return ValuePickleFile.with_pickle(tmp_path / "pickle", secret_key=SECRET_KEY)


@pytest.fixture(params=["memory", "cloudpickle", "dill", "pickle"])
def fast_call_storage(request, tmp_path):
    """Call storage backends for Hypothesis tests (HDF5 and SQL excluded)."""
    if request.param == "memory":
        return CallMemory({})
    elif request.param == "cloudpickle":
        return CallPickleFile.with_cloudpickle(tmp_path / "cloudpickle", secret_key=SECRET_KEY)
    elif request.param == "dill":
        return CallPickleFile.with_dill(tmp_path / "dill", secret_key=SECRET_KEY)
    elif request.param == "pickle":
        return CallPickleFile.with_pickle(tmp_path / "pickle", secret_key=SECRET_KEY)


# ---------------------------------------------------------------------------
# Functional roundtrip: save → pickle → unpickle → load (fast backends)
# ---------------------------------------------------------------------------


@settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(call=st_digested_calls)
def test_call_storage_functional_roundtrip(fast_call_storage, call):
    """Data saved to a call storage before pickling is accessible after restoring."""
    from fleche.storage import SaveError
    try:
        key = fast_call_storage.save(call)
    except SaveError:
        return
    restored = roundtrip(fast_call_storage)
    assert restored.load(key) == call


@settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(call=st_digested_calls)
def test_cache_functional_roundtrip(fast_value_storage, fast_call_storage, call):
    """Data saved to a cache before pickling is accessible after restoring."""
    cache = Cache(fast_value_storage, fast_call_storage)
    try:
        key = cache.save(call)
    except Rejected:
        return
    restored = roundtrip(cache)
    loaded = restored.load(key, lazy=False)
    assert loaded == call


@settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(call=st_digested_calls)
def test_cache_stack_functional_roundtrip(fast_value_storage, fast_call_storage, call):
    """CacheStack saves and loads correctly after pickling."""
    cache = Cache(fast_value_storage, fast_call_storage)
    try:
        key = cache.save(call)
    except Rejected:
        return
    stack = CacheStack((cache, Cache(ValueMemory({}), CallMemory({}))))
    restored = roundtrip(stack)
    loaded = restored.load(key, lazy=False)
    assert loaded == call


# ---------------------------------------------------------------------------
# Functional roundtrip for HDF5 and SQL backends (fixed examples)
#
# Representative Call shapes cover: empty args, populated args, None vs set
# module/version/result.  Property-based exploration is not needed here because
# H5Bag/SQL serialization is independent of Call structure variability.
# ---------------------------------------------------------------------------

_ROUNDTRIP_CALLS = [
    pytest.param(Call(name="minimal", arguments={}), id="minimal"),
    pytest.param(
        Call(name="full", arguments={"x": "a" * 64, "y": "b" * 64}, module="mymod", version=3, result="c" * 64),
        id="full",
    ),
]


@pytest.mark.parametrize("call", _ROUNDTRIP_CALLS)
def test_h5_call_storage_roundtrip(tmp_path, call):
    """HDF5 call storage: data saved before pickling is accessible after restoring."""
    storage = CallBagOfHoldingH5File(tmp_path / "h5")
    key = storage.save(call)
    assert roundtrip(storage).load(key) == call


@pytest.mark.parametrize("call", _ROUNDTRIP_CALLS)
def test_sql_call_storage_roundtrip(tmp_path, call):
    """SQL call storage: data saved before pickling is accessible after restoring."""
    storage = Sql(tmp_path / "calls.db")
    key = storage.save(call)
    assert roundtrip(storage).load(key) == call


def test_h5_cache_functional_roundtrip(tmp_path):
    """Cache backed by HDF5 value + call storage survives pickling."""
    vs = ValueBagOfHoldingH5File(tmp_path / "values")
    cs = CallBagOfHoldingH5File(tmp_path / "calls")
    cache = Cache(vs, cs)
    call = Call(name="f", arguments={"x": "a" * 64}, module="mod", version=1, result="b" * 64)
    key = cache.save(call)
    assert roundtrip(cache).load(key, lazy=False) == call


def test_h5_cache_stack_functional_roundtrip(tmp_path):
    """CacheStack with HDF5 base cache survives pickling and serves saved data."""
    vs = ValueBagOfHoldingH5File(tmp_path / "values")
    cs = CallBagOfHoldingH5File(tmp_path / "calls")
    h5_cache = Cache(vs, cs)
    stack = CacheStack((h5_cache, Cache(ValueMemory({}), CallMemory({}))))
    call = Call(name="f", arguments={"x": "a" * 64}, module=None, version=None, result="b" * 64)
    key = h5_cache.save(call)  # CacheStack.save() returns None; use the underlying cache
    assert roundtrip(stack).load(key, lazy=False) == call


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
