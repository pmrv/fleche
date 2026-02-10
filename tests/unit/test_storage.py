import pytest
from hypothesis import given, strategies as st
import numpy as np
import tempfile
from pathlib import Path

from fleche.storage import SaveError, CloudpickleFile, Memory, BagOfHoldingH5File
from fleche.digest import digest


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