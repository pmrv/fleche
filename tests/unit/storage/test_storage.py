import pytest
import string
from hypothesis import given, strategies as st
import numpy as np
from pathlib import Path

from fleche.storage import SaveError, PickleFile, Memory, BagOfHoldingH5File
from fleche.storage.sql import Sql
from fleche.call import Call
from fleche.digest import digest, Digest
from fleche.storage.base import DigestedIterable

from tests.strategies import st_data, st_digested_calls
from tests.fixtures import value_storages, call_storages


@pytest.mark.parametrize("value_storage", value_storages)
@given(st_data)
def test_storage(value_storage, value):
    try:
        key = value_storage.save(value)
    except SaveError:
        return  # not everyone can save everyone and that's ok, too
    loaded_value = value_storage.load(key)
    if isinstance(value, np.ndarray):
        np.testing.assert_array_equal(loaded_value, value)
    else:
        assert loaded_value == value


@pytest.mark.parametrize("value_storage", value_storages)
@given(st_data)
def test_storage_given_key(value_storage, value):
    # make up a unique key by hashing hash
    given_key = digest(str(digest(value)))
    try:
        key = value_storage.save(value, key=given_key)
    except SaveError:
        return  # not everyone can save everyone and that's ok, too
    assert key == given_key, "When forcing a key, storage must return the same key"

    loaded_value = value_storage.load(given_key)
    if isinstance(value, np.ndarray):
        np.testing.assert_array_equal(loaded_value, value)
    else:
        assert loaded_value == value, "value not available under given key"


@pytest.mark.parametrize("value_storage", value_storages)
@pytest.mark.parametrize(
    "value",
    [
        DigestedIterable([Digest("asdf"), Digest("foobar")]),
        DigestedIterable((Digest("asdf"), Digest("foobar"))),
    ],
)
def test_digested(value_storage, value):
    loaded_value = value_storage.load(value_storage.save(value))
    assert loaded_value == value, "digested value not available under given key"


# ------------------------
# CallStorage property tests
# ------------------------


@pytest.mark.parametrize("call_storage", call_storages)
@given(call=st_digested_calls)
def test_callstorages_random_calls_roundtrip(call_storage, call):
    try:
        key = call_storage.save(call)
    except SaveError:
        # Some backends may not support serializing arbitrary dataclasses; skip in that case
        return
    loaded = call_storage.load(key)
    assert loaded == call


@pytest.mark.parametrize("call_storage", call_storages)
@given(call=st_digested_calls)
def test_callstorages_short_prefix_load(call_storage, call):
    try:
        key = call_storage.save(call)
    except SaveError:
        return
    short = key[:8]
    loaded = call_storage.load(short)
    assert loaded == call


@pytest.mark.parametrize("call_storage", call_storages)
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
