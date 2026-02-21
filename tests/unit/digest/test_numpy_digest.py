import numpy as np
import pytest
from hypothesis import given, strategies as st
from hypothesis.extra import numpy as hnp
from fleche.digest import digest

@given(st.data())
def test_numpy_array_hashes_distinctly(data):
    # Generate two arrays
    arr1 = data.draw(hnp.arrays(dtype=hnp.scalar_dtypes(), shape=hnp.array_shapes()))
    arr2 = data.draw(hnp.arrays(dtype=hnp.scalar_dtypes(), shape=hnp.array_shapes()))

    # Check for distinctions in dtype, shape, or bytes content
    # Note: np.dtype objects can be compared directly for equality.
    # We use .str to be sure we are looking at the string representation if needed,
    # but the requirement says "if any of the following are distinct: dtype, shape, bytes content".
    distinct_dtype = arr1.dtype != arr2.dtype
    distinct_shape = arr1.shape != arr2.shape
    distinct_content = arr1.tobytes() != arr2.tobytes()

    if distinct_dtype or distinct_shape or distinct_content:
        assert digest(arr1) != digest(arr2), (
            f"Arrays should hash differently but didn't.\n"
            f"arr1: shape={arr1.shape}, dtype={arr1.dtype}, digest={digest(arr1)}\n"
            f"arr2: shape={arr2.shape}, dtype={arr2.dtype}, digest={digest(arr2)}\n"
            f"Differences: dtype={distinct_dtype}, shape={distinct_shape}, content={distinct_content}"
        )
    else:
        # If they are same in all three, they MUST hash the same
        assert digest(arr1) == digest(arr2)

def test_numpy_explicit_cases():
    # Explicitly test the cases that were failing

    # Same content, different dtype
    a = np.array([0], dtype='int32')
    b = np.array([0], dtype='float32')
    assert a.tobytes() == b.tobytes()
    assert a.dtype != b.dtype
    assert digest(a) != digest(b)

    # Same content, different shape
    c = np.array([1, 2, 3, 4], dtype='int64')
    d = np.array([[1, 2], [3, 4]], dtype='int64')
    assert c.tobytes() == d.tobytes()
    assert c.shape != d.shape
    assert digest(c) != digest(d)
