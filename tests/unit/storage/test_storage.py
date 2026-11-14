import pytest
from hypothesis import given, settings, HealthCheck
import numpy as np

from fleche.storage import SaveError, CallMemory
from fleche.storage.sql import Sql
from fleche.call import Call
from fleche.digest import Digest, digest

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


@settings(deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(call=st_digested_calls)
def test_backend_stores_call_objects(storage_backend, call):
    key = call.to_lookup_key()
    try:
        storage_backend.put(call, key)
    except SaveError:
        return
    loaded = storage_backend.get(key)
    assert loaded == call


@settings(deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(value=st_data)
def test_backend_short_prefix_expand(storage_backend, value):
    key = digest(value)
    try:
        storage_backend.put(value, key)
    except SaveError:
        return
    assert storage_backend.expand(key[:8]) == key


class Unserialisable:
    """Stands in for a C extension object: copying or pickling it raises, as ``ACEBEvaluator`` does."""

    def __reduce__(self):
        raise TypeError("cannot pickle 'Unserialisable' object")


@pytest.mark.parametrize("error", [TypeError, AttributeError, RecursionError])
def test_backend_refusal_is_a_save_error(storage_backend, error):
    """Whatever ``__reduce__`` raises, the backend reports ``SaveError``: it is what callers catch."""

    class Refuses:
        def __reduce__(self):
            raise error("refused")

    with pytest.raises(SaveError) as excinfo:
        storage_backend.put(Refuses(), Digest("ab" * 32))
    assert excinfo.value.__cause__ is not None, "the original stays reachable for diagnosis"


def test_backend_refusal_leaves_nothing_behind(storage_backend):
    """A refused put stores no entry, partial or temporary, and spares a neighbour sharing its file."""
    neighbour, refused = Digest("ab" * 32), Digest("ab" + "cd" * 31)
    storage_backend.put("kept", neighbour)
    with pytest.raises(SaveError):
        storage_backend.put(Unserialisable(), refused)
    assert not storage_backend.contains(refused)
    assert list(storage_backend.list()) == [neighbour]
    assert storage_backend.get(neighbour) == "kept"
    root = getattr(storage_backend, "root", None)
    if root is not None:
        assert not [p for p in root.rglob(".*") if p.suffix == ".tmp"]


def test_callstorages_evict():
    store = CallMemory({})
    call = Call(
        name="evict_me",
        arguments={"a": "a" * 64},
        metadata={},
        module=None,
        version=None,
        result=None,
    )
    key = store.save(call)
    assert key in set(store.list())

    # Test short-hand eviction
    short_key = key[:8]
    store.evict(short_key)
    assert key not in set(store.list())
    with pytest.raises(KeyError):
        store.load(key)

    # Test idempotent eviction (full key)
    store.evict(key)  # Should not raise anything

    # Re-save and test full key eviction
    key = store.save(call)
    assert key in set(store.list())
    store.evict(key)
    assert key not in set(store.list())
    with pytest.raises(KeyError):
        store.load(key)


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


