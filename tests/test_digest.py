from hypothesis import given
from hypothesis import strategies as st
import numpy as np
from dataclasses import dataclass
import math
import hashlib

from fleche.digest import digest


def test_supported_types():
    """Test that all supported types can be digested without raising an exception."""
    @dataclass
    class MyData:
        x: int
        y: str

    supported_examples = [
        "hello",
        123,
        123.456,
        True,
        None,
        ("a", 1, None),
        ["a", 1, None],
        {"a": 1, "b": None},
        np.array([1, 2, 3]),
        MyData(x=1, y="a"),
    ]

    for example in supported_examples:
        digest(example)


@given(st.integers(), st.integers())
def test_different_integers_have_different_hashes(x, y):
    """Test that two different integers have different hashes."""
    if x == y:
        assert digest(x) == digest(y)
    else:
        assert digest(x) != digest(y)


@given(st.floats(allow_nan=True), st.floats(allow_nan=True))
def test_different_floats_have_different_hashes(x, y):
    """Test that two different floats have different hashes."""
    if x == y or (math.isnan(x) and math.isnan(y) and math.copysign(1, x) == math.copysign(1, y)):
        assert digest(x) == digest(y)
    else:
        assert digest(x) != digest(y)


@given(st.lists(st.integers()))
def test_different_iterables_same_values_hash_differently(lst):
    """Test that two different iterables with the same values have different hashes."""
    tup = tuple(lst)
    assert digest(tup) != digest(lst)


def test_specific_iterables_dont_use_generic_iterable_path(monkeypatch):
    """Test that specific iterable types use their specific match case."""
    # spy on the update method
    update_calls = []

    class MockSHA256:
        def update(self, data):
            update_calls.append(data)

        def hexdigest(self):
            return "mock_hexdigest"

    monkeypatch.setattr(hashlib, "sha256", MockSHA256)

    # test str
    update_calls.clear()
    digest("hello")
    assert b"str" not in update_calls

    # test bytes
    update_calls.clear()
    digest(b"hello")
    assert b"bytes" not in update_calls

    # test dict
    update_calls.clear()
    digest({"a": 1})
    assert b"dict" not in update_calls

    # test numpy array
    update_calls.clear()
    digest(np.array([1, 2, 3]))
    assert b"ndarray" not in update_calls
