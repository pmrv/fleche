import pytest
from hypothesis import given, strategies as st
import numpy as np
import tempfile
from pathlib import Path

from fleche.storage import SaveError, CloudpickleFile, Memory, BagOfHoldingH5File
from fleche.storage.sql import Sql
from fleche.call import Call
from fleche.digest import digest, Digest
from fleche.caches import DigestedIterable
from fleche.metadata import Runtime, CallInfo


temp = tempfile.TemporaryDirectory()
temp_bag = tempfile.TemporaryDirectory()
storages = [Memory({}), CloudpickleFile(temp.name), BagOfHoldingH5File(temp_bag.name)]

st_data = st.one_of(
    st.integers(),
    st.floats(allow_nan=False),
    st.text(),
    st.binary(),
    st.booleans(),
    st.lists(st.integers()),
    st.tuples(st.integers(), st.text()),
    st.dictionaries(st.text(), st.integers()),
    st.builds(np.array, st.lists(st.integers())),
)

@pytest.mark.parametrize("storage", storages)
@given(st_data)
def test_storage(storage, value):
    try:
        key = storage.save(value)
    except SaveError:
        return # not everyone can save everyone and that's ok, too
    loaded_value = storage.load(key)
    if isinstance(value, np.ndarray):
        np.testing.assert_array_equal(loaded_value, value)
    else:
        assert loaded_value == value


@pytest.mark.parametrize("storage", storages)
@given(st_data)
def test_storage_given_key(storage, value):
    # make up a unique key by hashing hash
    given_key = digest(str(digest(value)))
    try:
        key = storage.save(value, key=given_key)
    except SaveError:
        return # not everyone can save everyone and that's ok, too
    assert key == given_key, "When forcing a key, storage must return the same key"

    loaded_value = storage.load(given_key)
    if isinstance(value, np.ndarray):
        np.testing.assert_array_equal(loaded_value, value)
    else:
        assert loaded_value == value, "value not available under given key"


@pytest.mark.parametrize("storage", storages)
@pytest.mark.parametrize("value", [
    DigestedIterable([Digest("asdf"), Digest("foobar")]),
    DigestedIterable((Digest("asdf"), Digest("foobar"))),
])
def test_digested(storage, value):
    loaded_value = storage.load(storage.save(value))
    assert loaded_value == value, "digested value not available under given key"


# ------------------------
# CallStorage property tests
# ------------------------

# Dedicated temp roots for call storages
temp_calls_root = tempfile.TemporaryDirectory()
temp_calls_h5 = tempfile.TemporaryDirectory()
temp_calls_sql = tempfile.TemporaryDirectory()

call_storages = [
    Memory({}),
    CloudpickleFile(temp_calls_root.name),
    BagOfHoldingH5File(temp_calls_h5.name),
    Sql(Path(temp_calls_sql.name) / "calls.db"),
]

# Strategies for generating Call instances with digest-string args/kwargs/result
st_call_name = st.text(min_size=1, max_size=10)
st_hex = st.text(min_size=64, max_size=64, alphabet="0123456789abcdef")
st_call_args = st.lists(st_hex, max_size=3).map(tuple)
st_call_kwargs = st.dictionaries(st.text(min_size=1, max_size=5), st_hex, max_size=3)


@pytest.mark.parametrize("call_storage", call_storages)
@given(
    name=st_call_name,
    args=st_call_args,
    kwargs=st_call_kwargs,
    module=st.one_of(st.none(), st.text(min_size=1, max_size=10)),
    version=st.one_of(st.none(), st.integers(min_value=0, max_value=100)),
    result=st.one_of(st.none(), st_hex),
)
def test_callstorages_random_calls_roundtrip(call_storage, name, args, kwargs, module, version, result):
    call = Call(name=name, args=args, kwargs=kwargs, metadata={}, module=module, version=version, result=result)
    try:
        key = call_storage.save(call)
    except SaveError:
        # Some backends may not support serializing arbitrary dataclasses; skip in that case
        return
    loaded = call_storage.load(key)
    assert loaded == call


@pytest.mark.parametrize("call_storage", call_storages)
@given(
    name=st_call_name,
    args=st_call_args,
    kwargs=st_call_kwargs,
    module=st.one_of(st.none(), st.text(min_size=1, max_size=10)),
    version=st.one_of(st.none(), st.integers(min_value=0, max_value=100)),
    result=st.one_of(st.none(), st_hex),
)
def test_callstorages_short_prefix_load(call_storage, name, args, kwargs, module, version, result):
    call = Call(name=name, args=args, kwargs=kwargs, metadata={}, module=module, version=version, result=result)
    try:
        key = call_storage.save(call)
    except SaveError:
        return
    short = key[:8]
    loaded = call_storage.load(short)
    assert loaded == call


def test_sql_evict(tmp_path):
    # Evict is specific to Sql backend
    store = Sql(str(tmp_path / "calls.db"))
    call = Call(name="evict_me", args=("a" * 64,), kwargs={}, metadata={}, module=None, version=None, result=None)
    key = store.save(call)
    assert key in set(store.list())
    store.evict(key)
    with pytest.raises(KeyError):
        store.load(key)


def test_sql_metadata_roundtrip_and_query(tmp_path):
    store = Sql(str(tmp_path / "calls.db"))

    # Create two calls with metadata
    c1 = Call(name="f1", args=("a" * 64,), kwargs={}, metadata={
        "runtime": {"walltime": 1.23, "timestart": 0.1, "timestop": 1.33},
        "tags": {"project": "alpha", "phase": "train"},
    }, module=None, version=None, result=None)

    c2 = Call(name="f2", args=("b" * 64,), kwargs={}, metadata={
        "runtime": {"walltime": 2.0},
        "tags": {"project": "beta", "phase": "eval"},
    }, module=None, version=None, result=None)

    k1 = store.save(c1)
    k2 = store.save(c2)

    lc1 = store.load(k1)
    lc2 = store.load(k2)
    assert lc1.metadata == c1.metadata
    assert lc2.metadata == c2.metadata

    # Query by metadata name and key
    keys_alpha = set(store.find_by_metadata(name="tags", project="alpha"))
    assert k1 in keys_alpha and k2 not in keys_alpha

    # Query across all names (e.g., by walltime value)
    keys_walltime_2 = set(store.find_by_metadata(walltime=2.0))
    assert k2 in keys_walltime_2 and k1 not in keys_walltime_2
