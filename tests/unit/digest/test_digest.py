import cmath
import struct

import pytest
from hypothesis import given
from hypothesis import strategies as st
from hypothesis.extra import numpy as hnp
from tests.strategies import st_nested_values
import numpy as np
from dataclasses import dataclass, make_dataclass, is_dataclass, fields
import math
import string
import keyword


from fleche import fleche
from fleche.digest import digest, Digest
from fleche.call import Call


def test_custom_digest():
    """Test that custom __digest__ method is used."""

    class CustomMethod:
        def __init__(self, d):
            self.d = d

        def __digest__(self):
            return self.d

    assert digest(CustomMethod("method")) == "method"
    assert isinstance(digest(CustomMethod("method")), Digest)


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
    # Handle NaN comparison and sign comparison
    both_nan = math.isnan(x) and math.isnan(y)
    same_sign = math.copysign(1, x) == math.copysign(1, y)

    if (both_nan and same_sign) or x == y:
        assert digest(x) == digest(y)
    else:
        assert digest(x) != digest(y)


@given(st.complex_numbers(allow_nan=True), st.complex_numbers(allow_nan=True))
def test_different_complex_numbers_have_different_digests(x, y):
    """Test that two different complex numbers have different digests."""
    if cmath.isnan(x) or cmath.isnan(y):
        # NaN case: digest is based on raw binary packing of real and imaginary parts
        x_bytes = struct.pack("<dd", x.real, x.imag)
        y_bytes = struct.pack("<dd", y.real, y.imag)
        if x_bytes == y_bytes:
            assert digest(x) == digest(y)
        else:
            assert digest(x) != digest(y)
    else:
        # Non-NaN: follows Python hash semantics (hash(1) == hash(1+0j))
        if hash(x) == hash(y):
            assert digest(x) == digest(y)
        else:
            assert digest(x) != digest(y)


@given(st.complex_numbers(allow_nan=True))
def test_complex_numbers_can_be_digested(x):
    """Test that complex numbers (including NaN) can be digested without error."""
    digest(x)


def test_complex_matches_real_without_imaginary_part():
    """Test that digest(1) == digest(1+0j) per standard Python hash semantics."""
    assert digest(1) == digest(1 + 0j)
    assert digest(1.0) == digest(1 + 0j)
    assert digest(2) == digest(2 + 0j)


def test_int_matches_float_without_fractional_part():
    """Test that digest(1) == digest(1.0) per standard Python hash semantics."""
    assert digest(1) == digest(1.0)
    assert digest(2) == digest(2.0)
    assert digest(-3) == digest(-3.0)


@given(
    st.one_of(
        st.builds(np.complex64, st.complex_numbers(allow_nan=False)),
        st.builds(np.complex128, st.complex_numbers(allow_nan=False)),
    )
)
def test_numpy_complex_can_be_digested(x):
    """Test that numpy complex numbers can be digested and match their Python complex equivalent."""
    assert digest(x) == digest(complex(x))


@given(st.lists(st.integers()))
def test_different_iterables_same_values_hash_differently(lst):
    """Test that two different iterables with the same values have different hashes."""
    tup = tuple(lst)
    assert digest(tup) != digest(lst)


def test_specific_iterables_dont_use_generic_iterable_path(monkeypatch):
    """Test that specific iterable types use their specific match case."""

    # fake class that acts and names itself as the original type's iterator
    class Chamelion:
        def __init__(self, value):
            self.value = value

        @property
        def __name__(self):
            return type(self.value).__name__

        def __iter__(self):
            return iter(self.value)

    # test str
    assert digest("hello") != Chamelion("hello")
    assert digest(b"hello") != Chamelion(b"hello")
    assert digest({"a": 1}) != Chamelion({"a": 1})
    assert digest(np.array([1, 2, 3])) != Chamelion(np.array([1, 2, 3]))


def randomly_digest_subvalues(value, data):
    """
    Recursively walk a nested structure and randomly replace sub-values with their digests.

    Uses st.data() to draw boolean decisions at each node, making the replacement
    pattern explicit in Hypothesis falsifying examples.

    Args:
        value: The nested value to process
        data: Hypothesis data object for drawing from strategies

    Returns:
        A modified copy of the value with some sub-values replaced by their digests
    """
    # Base case: randomly decide whether to replace this value with its digest
    if data.draw(st.booleans()):
        return digest(value)

    # Otherwise, recurse into the structure
    if isinstance(value, list):
        return [randomly_digest_subvalues(v, data) for v in value]
    elif isinstance(value, tuple) and hasattr(value, "_fields") and hasattr(value, "_field_defaults"):
        # namedtuple: reconstruct preserving the concrete type, since digest() includes type.__name__
        return type(value)(*[randomly_digest_subvalues(v, data) for v in value])
    elif isinstance(value, tuple):
        return tuple(randomly_digest_subvalues(v, data) for v in value)
    elif isinstance(value, dict):
        # For dicts, only replace values (keys must remain the same)
        return {k: randomly_digest_subvalues(v, data) for k, v in value.items()}
    elif is_dataclass(value) and not isinstance(value, type):
        # For dataclasses, replace field values
        field_dict = {
            f.name: randomly_digest_subvalues(getattr(value, f.name), data)
            for f in fields(value)
        }
        return type(value)(**field_dict)
    elif isinstance(value, Call):
        # For Call, replace argument values
        return Call(
            name=value.name,
            arguments={
                k: randomly_digest_subvalues(v, data)
                for k, v in value.arguments.items()
            },
            module=value.module,
            version=value.version,
        )
    else:
        # Base value, return as-is
        return value


@given(st_nested_values, st.data())
def test_merkle_tree_property(value, data):
    """
    Test the merkle tree property: replacing any sub-value with its digest preserves the overall digest.

    This property is essential for building merkle trees where we can replace
    any subtree with its digest and get the same overall hash.

    This unified test generates random nested values and randomly replaces sub-values
    with their digests, verifying that the overall digest remains unchanged.
    """
    original_digest = digest(value)
    modified_value = randomly_digest_subvalues(value, data)
    assert digest(modified_value) == original_digest, (
        "Merkle property failed: digest changed after replacing sub-values with their digests",
        value,
        modified_value,
    )


# some explicit cases test_merkle_tree_property is apparently not efficient enough to catch


@dataclass
class Input:
    a: int


@dataclass
class Other:
    i: Input


@fleche
def foo(inp, **kwargs):
    return inp.a / inp.b


@pytest.mark.parametrize(
    "value, partially_digested_value",
    (
        ([Input(2)], [digest(Input(2))]),
        ((Input(2),), (digest(Input(2)),)),
        (Other(Input(2)), Other(Input(digest(2)))),
        (Other(Input(2)), Other(digest(Input(2)))),
        (foo.fleche.call(Input(1), a=Input(2)), foo.fleche.call(digest(Input(1)), a=Input(2))),
        (foo.fleche.call(Input(1), a=Input(2)), foo.fleche.call(Input(1), a=digest(Input(2)))),
    ),
)
def test_merkle_tree_property_fixed(value, partially_digested_value):
    assert digest(value) == digest(partially_digested_value), (
        value,
        partially_digested_value,
    )


@given(
    st.dictionaries(
        st.text(string.ascii_letters, min_size=1).filter(
            lambda x: not keyword.iskeyword(x)
        ),
        st.integers(),
    )
)
def test_dataclasses_with_different_names_have_different_digests(fields_dict):
    """Test that two dataclasses with different names but identical fields do not hash to the same value."""
    if not fields_dict:
        return

    fields_list = [(k, type(v)) for k, v in fields_dict.items()]

    A = make_dataclass("ClassA", fields_list, frozen=True)
    B = make_dataclass("ClassB", fields_list, frozen=True)

    a = A(**fields_dict)
    b = B(**fields_dict)

    assert digest(a) != digest(b)


@given(st.data())
def test_numpy_array_hashes_distinctly(data):
    """Test that numpy arrays with distinct dtype, shape, or content have different digests."""
    arr1 = data.draw(hnp.arrays(dtype=hnp.scalar_dtypes(), shape=hnp.array_shapes()))
    arr2 = data.draw(hnp.arrays(dtype=hnp.scalar_dtypes(), shape=hnp.array_shapes()))

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
        assert digest(arr1) == digest(arr2)


def test_numpy_explicit_cases():
    """Test digest distinguishes arrays that differ only in dtype or shape (not raw bytes)."""
    # Same content, different dtype
    a = np.array([0], dtype="int32")
    b = np.array([0], dtype="float32")
    assert a.tobytes() == b.tobytes()
    assert a.dtype != b.dtype
    assert digest(a) != digest(b)

    # Same content, different shape
    c = np.array([1, 2, 3, 4], dtype="int64")
    d = np.array([[1, 2], [3, 4]], dtype="int64")
    assert c.tobytes() == d.tobytes()
    assert c.shape != d.shape
    assert digest(c) != digest(d)


def test_lambda_can_be_digested():
    """Test that lambda functions can be digested without raising Unhashable."""
    f = lambda x: x + 1
    result = digest(f)
    assert isinstance(result, Digest)


def test_locally_defined_function_can_be_digested():
    """Test that locally defined functions can be digested without raising Unhashable."""
    def local_func(x):
        return x * 2

    result = digest(local_func)
    assert isinstance(result, Digest)


def test_nested_function_can_be_digested():
    """Test that functions nested inside other functions can be digested."""
    def outer():
        def inner(x):
            return x + 1
        return inner

    result = digest(outer())
    assert isinstance(result, Digest)


def test_function_digest_is_stable():
    """Test that digesting the same function repeatedly returns the same value."""
    def local_func(x):
        return x * 2

    assert digest(local_func) == digest(local_func)


def test_functions_with_different_bodies_have_different_digests():
    """Test that functions with distinct bodies hash differently."""
    f = lambda x: x + 1
    g = lambda x: x + 2
    assert digest(f) != digest(g)


def test_functions_with_identical_bodies_have_same_digest():
    """Test that two locally defined functions with identical code objects hash the same."""
    def f(x):
        return x + 1

    def g(x):
        return x + 1

    assert digest(f) == digest(g)


def test_local_function_digests_same_as_module_level():
    """Test that a local function with identical code digests the same as a module-level equivalent."""
    def local_add_one(x):
        return x + 1

    def _module_level_add_one(x):
        return x + 1

    assert digest(local_add_one) == digest(_module_level_add_one)
