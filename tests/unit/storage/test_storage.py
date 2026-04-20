import pytest
from hypothesis import given, settings, HealthCheck
import numpy as np

from fleche.storage import SaveError
from fleche.storage.sql import Sql
from fleche.call import Call
from fleche.digest import digest

from tests.strategies import st_data, st_digested_calls


# ------------------------
# StorageBackend property tests
# ------------------------


@settings(deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(value=st_data)
def test_backend_put_get_roundtrip(storage_backend, value):
    key = digest(value)
    try:
        returned_key = storage_backend.put(value, key)
    except SaveError:
        return
    assert returned_key == key
    loaded = storage_backend.get(key)
    if isinstance(value, np.ndarray):
        np.testing.assert_array_equal(loaded, value)
    else:
        assert loaded == value


@settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(call=st_digested_calls)
def test_backend_stores_call_objects(storage_backend, call):
    key = call.to_lookup_key()
    try:
        storage_backend.put(call, key)
    except SaveError:
        return
    loaded = storage_backend.get(key)
    assert loaded == call


@settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(value=st_data)
def test_backend_short_prefix_expand(storage_backend, value):
    key = digest(value)
    try:
        storage_backend.put(value, key)
    except SaveError:
        return
    assert storage_backend.expand(key[:8]) == key


def test_callstorages_evict(call_storage):
    call = Call(
        name="evict_me",
        arguments={"a": "a" * 64},
        metadata={},
        module=None,
        version=None,
        result=None,
    )
    try:
        key = call_storage.save(call)
    except SaveError:
        return
    assert key in set(call_storage.list())

    # Test short-hand eviction
    short_key = key[:8]
    call_storage.evict(short_key)
    assert key not in set(call_storage.list())
    with pytest.raises(KeyError):
        call_storage.load(key)

    # Test idempotent eviction (full key)
    call_storage.evict(key)  # Should not raise anything

    # Re-save and test full key eviction
    key = call_storage.save(call)
    assert key in set(call_storage.list())
    call_storage.evict(key)
    assert key not in set(call_storage.list())
    with pytest.raises(KeyError):
        call_storage.load(key)


def test_sql_metadata_roundtrip_and_query(tmp_path):
    store = Sql(str(tmp_path / "calls.db"))

    # Create two calls with metadata
    c1 = Call(
        name="f1",
        arguments={"a": "a" * 64},
        metadata={
            "runtime": {"walltime": 1.23, "timestart": 0.1, "timestop": 1.33},
            "tags": {"project": "alpha", "phase": "train"},
        },
        module=None,
        version=None,
        result=None,
    )

    c2 = Call(
        name="f2",
        arguments={"b": "b" * 64},
        metadata={
            "runtime": {"walltime": 2.0},
            "tags": {"project": "beta", "phase": "eval"},
        },
        module=None,
        version=None,
        result=None,
    )

    k1 = store.save(c1)
    k2 = store.save(c2)

    lc1 = store.load(k1)
    lc2 = store.load(k2)
    assert lc1.metadata == c1.metadata
    assert lc2.metadata == c2.metadata

    # Query by metadata name and key using query(template)
    t1 = Call(
        name=None,
        arguments=None,
        metadata={"tags": {"project": "alpha"}},
        module=None,
        version=None,
        result=None,
    )
    names_alpha = {c.name for c in store.query(t1)}
    assert names_alpha == {"f1"}

    # Query across all names (e.g., by walltime value) using query(template)
    t2 = Call(
        name=None,
        arguments=None,
        metadata={"runtime": {"walltime": 2.0}},
        module=None,
        version=None,
        result=None,
    )
    names_walltime_2 = {c.name for c in store.query(t2)}
    assert names_walltime_2 == {"f2"}


