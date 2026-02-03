import pytest
from hypothesis import given, strategies as st
import numpy as np
import tempfile
from pathlib import Path
import shutil

from fleche.storage import CloudpickleFileStorage, MemoryStorage


temp = tempfile.TemporaryDirectory()
storages = [MemoryStorage({}), CloudpickleFileStorage(temp.name)]


@pytest.mark.parametrize("storage", storages)
@given(st.one_of(
    st.integers(),
    st.floats(allow_nan=False),
    st.text(),
    st.binary(),
    st.booleans(),
    st.lists(st.integers()),
    st.tuples(st.integers(), st.text()),
    st.dictionaries(st.text(), st.integers()),
    st.builds(np.array, st.lists(st.integers())),
))
def test_storage(storage, value):
    storage.save("key", value)
    loaded_value = storage.load("key")
    if isinstance(value, np.ndarray):
        np.testing.assert_array_equal(loaded_value, value)
    else:
        assert loaded_value == value
