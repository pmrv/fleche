"""``digest()`` dispatch: what each kind of value contributes to its digest.

Layer note: this file owns the *value* end — given a function, a closure, a
bound method, what comes out.  How ``code_digest`` is derived from a callable
is ``tests/unit/call/test_code_digest.py``; whether the decorator carries it
into the key is ``tests/unit/fleche/test_hash_code.py``.
"""

import abc
import cmath
import enum
import sys
import time
import inspect
import pathlib
import datetime
import struct
import collections
import numbers as numbers_module
import collections.abc
import types as types_module

import pytest
from hypothesis import example, given
from hypothesis import strategies as st
from hypothesis.extra import numpy as hnp
from tests.strategies import st_nested_values
import numpy as np
import pandas as pd
from dataclasses import dataclass, make_dataclass, is_dataclass, fields
import math
import string
import keyword
from decimal import Decimal
from fractions import Fraction


from fleche import fleche
from fleche.state import cache
from fleche.digest import digest, Digest, Indigestible
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


def test_custom_digest_priority():
    """Test that __digest__ has priority over default implementations."""

    class CustomStr(str):
        def __digest__(self):
            return "custom_str_digest"

    class CustomInt(int):
        def __digest__(self):
            return "custom_int_digest"

    class CustomDict(dict):
        def __digest__(self):
            return "custom_dict_digest"

    assert digest(CustomStr("hello")) == "custom_str_digest"
    assert digest(CustomInt(42)) == "custom_int_digest"
    assert digest(CustomDict(a=1)) == "custom_dict_digest"


@dataclass
class _SupportedData:
    x: int
    y: str


# Built-in type objects (the classes themselves) are digestible per issue #469;
# anything outside the ``builtins`` module raises ``Indigestible`` (see the
# negative boundary test near the end of this file).
BUILTIN_TYPES = (int, str, float, bool, bytes, list, dict, tuple, set, type, object)

# One representative value per digestible category, all mutually distinct.  Used
# by the digestibility, stability and distinctness contracts below.
SUPPORTED_VALUES = [
    "hello",
    123,
    123.456,
    True,
    None,
    ("a", 1, None),
    ["a", 1, None],
    {"a": 1, "b": None},
    np.array([1, 2, 3]),
    _SupportedData(x=1, y="a"),
    *BUILTIN_TYPES,
]


def test_supported_types():
    """All supported values can be digested without raising an exception."""
    for value in SUPPORTED_VALUES:
        digest(value)


def test_supported_values_digest_stably():
    """Digesting the same value twice yields the same digest."""
    unstable = [repr(value) for value in SUPPORTED_VALUES if digest(value) != digest(value)]
    assert not unstable, f"digest is not deterministic for: {unstable}"


def test_supported_values_digest_distinctly():
    """No two of the supported values share a digest.

    Built-in type objects (issue #469) are folded into SUPPORTED_VALUES, so their
    distinctness from one another and from instances — the type-vs-instance case —
    is covered here rather than in a bespoke builtins-only test.

    Uniqueness over the whole list is exactly the pairwise contract: every pair of
    distinct values digests differently iff no two digests collide.  Asserting it
    on the set rather than on all ``len(SUPPORTED_VALUES) ** 2`` ordered pairs
    names the colliding values on failure instead of a pair of indices, and keeps
    the suite from being dominated by a product parametrisation that covers no
    code path the focused per-type tests in this file do not already reach.
    """
    digests = [digest(value) for value in SUPPORTED_VALUES]
    collisions = {
        d: [repr(v) for v, dv in zip(SUPPORTED_VALUES, digests) if dv == d]
        for d in digests
        if digests.count(d) > 1
    }
    assert not collisions, f"supported values sharing a digest: {collisions}"


@given(st.integers(), st.integers())
def test_different_integers_have_different_hashes(x, y):
    """Test that two different integers have different hashes."""
    if x == y:
        assert digest(x) == digest(y)
    else:
        assert digest(x) != digest(y)


@given(st.floats(allow_nan=True), st.floats(allow_nan=True))
# collision instances from previous numbers' digest
@example(-1.0, -2.0)
@example(0.5, 2.0**60)
@example(2.0**100, 2.0**39)
@example(2.0**61, 1.0)
@example(math.inf, 314159.0)
@example(-math.inf, -314159.0)
@example(-0.0, 0.0)
def test_different_floats_have_different_hashes(x, y):
    """Test that two different floats have different hashes."""
    if math.isnan(x) or math.isnan(y):
        # NaN case: digest is based on raw binary packing
        x_bytes = struct.pack("<d", x)
        y_bytes = struct.pack("<d", y)
        if x_bytes == y_bytes:
            assert digest(x) == digest(y)
        else:
            assert digest(x) != digest(y)
    elif x == y:
        assert digest(x) == digest(y)
    else:
        assert digest(x) != digest(y)


@given(st.complex_numbers(allow_nan=True), st.complex_numbers(allow_nan=True))
# collision instances from previous numbers' digest
@example(1j, 1000003 + 0j)
@example(-1 + 0j, -2 + 0j)
@example(0.5 + 0j, 2.0**60 + 0j)
@example(complex(math.inf, 0), 314159 + 0j)
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
    elif x == y:
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


# Unequal numbers that shared a digest under hash() (PR #990) or a draft of
# its replacement.
COLLISIONS = [
    (-1.0, -2.0),  # CPython remaps the error sentinel hash -1 to -2
    (Fraction(-1), -2),
    (Decimal(-1), -2),
    (np.float32(-1), -2),
    (-1 + 0j, -2),
    (0.5, 2**60),  # a fraction hashes to num * den**-1 mod 2**61 - 1
    (Fraction(1, 3), 1537228672809129301),
    (2.0**100, 2.0**39),  # reduction mod 2**61 - 1
    (2.0**61, 1),
    (np.uint64(2**63), 4),  # np.integer used to take the hash() path
    (math.inf, 314159),  # sys.hash_info.inf
    (-math.inf, -314159),
    (1j, 1000003),  # hash(a + bj) == hash(a) + 1000003 * hash(b)
    (Decimal("1e400"), math.inf),  # finite, though float() overflows it
    (0.1, Decimal("0.1")),  # the float is not exactly 1/10
]


@pytest.mark.parametrize("a, b", COLLISIONS)
def test_unequal_numbers_have_different_digests(a, b):
    assert a != b
    assert digest(a) != digest(b)


@pytest.mark.parametrize("a, b", COLLISIONS)
def test_unequal_numbers_do_not_share_a_cache_entry(clean_cache, a, b):
    # The end-to-end symptom on PR #990: the second call was a cache hit on the
    # first and returned its result.
    @fleche
    def identity(x):
        return x

    with cache(clean_cache):
        assert identity(a) == a
        assert identity(b) == b


@pytest.mark.parametrize(
    "a, b",
    [
        (-1.0, -1),  # hash(-1.0) was -2, while the int path never hashed
        (np.float32(-1), -1),
        (-1 + 0j, -1),
        (float(2**70), 2**70),
        (Fraction(-1), -1),
        (Decimal(-1), -1),
        (0.5, Fraction(1, 2)),
        (0.5, Decimal("0.5")),
        (0.5, np.float32(0.5)),
        (0.5, 0.5 + 0j),
        (np.float16(0.75), Fraction(3, 4)),
        (np.longdouble(0.25), 0.25),
        (-0.0, 0),
        (-0.0, 0.0),
        (math.inf, Decimal("Infinity")),
        (-math.inf, np.float32("-inf")),
        (np.uint64(2**63), 2**63),
        (1.5 + 2j, np.complex64(1.5 + 2j)),
        (Decimal("1e400"), 10**400),  # float() would overflow, int() does not
        (Decimal("0.10"), Decimal("0.1")),  # same value, different exponent
        (Fraction(1, 10), Decimal("0.1")),  # neither fits in a float
    ],
)
def test_equal_numbers_have_equal_digests(a, b):
    assert a == b
    assert digest(a) == digest(b)


# np.longdouble is x87 extended precision on x86-64, IEEE quad on aarch64 Linux
# and a plain double on Windows and macOS: the values it can hold differ between
# machines, the digest of a given value does not (see the pinned digests below).
EXTENDED_LONGDOUBLE = np.finfo(np.longdouble).nmant > np.finfo(np.float64).nmant


@pytest.mark.skipif(not EXTENDED_LONGDOUBLE, reason="np.longdouble is a double here")
def test_wide_numpy_float_digests_as_its_exact_fraction():
    x = np.longdouble(1) / 3
    assert float(x) != x
    assert digest(x) == digest(Fraction(*x.as_integer_ratio()))
    # A zero imaginary part must not strand the real part on the complex path,
    # which has no node to hold it.
    assert digest(np.clongdouble(x)) == digest(x)


# Digests are a function of the exact value alone, so they must not drift with
# the machine, the Python version or numpy's scalar widths; CI runs this file
# across the supported versions.
PINNED_DIGESTS = {
    "1": (1, "da217d50752f3371d9f8b62a3e72409592bd34b74e14fdac43e2b137bd59f21f"),
    "0.5": (0.5, "fc7c2237b80899d0cc04c63eda2548c0e5cdb0a58c82db3bd43824d8220923b7"),
    "Fraction(1, 3)": (Fraction(1, 3), "4c0d2ccfd91ca3d1959ccef24c7d962bcb2a067c7b62b0ca614769dca83fe557"),
    "1.5+2j": (1.5 + 2j, "b25b8e15b33f4117e21e8c8d2eae4def45ef25823d06b19199d870294e224bd4"),
    "inf": (math.inf, "8561a7bd5204505bdfef420e39d2683bdb576faba2705ddcaaab42c0b1159f9e"),
    "nan": (math.nan, "39927fc4a0964029f26f8ba2e346344bc65e3d27c6a075b30e836f84afa18746"),
    "Decimal('sNaN')": (Decimal("sNaN"), "28a509caace33df4dab1133d77c6a2eb6c3b886eabee7f68d6875ca7cae835c2"),
}


@pytest.mark.parametrize("name", PINNED_DIGESTS)
def test_number_digests_are_pinned(name):
    value, expected = PINNED_DIGESTS[name]
    assert digest(value) == expected


def _label(t):
    return t.__name__ if t.__module__ == "builtins" else f"{t.__module__}.{t.__name__}"


def _draw_number_tree(node, prefix=""):
    lines = []
    for i, child in enumerate(node.children):
        last = i == len(node.children) - 1
        lines.append(prefix + ("└── " if last else "├── ") + _label(child.type))
        lines += _draw_number_tree(child, prefix + ("    " if last else "│   "))
    return lines


def test_number_tree_matches_its_drawings():
    from fleche import _numbers

    lines = [_label(_numbers.NUMBER_TREE.type)]
    lines += _draw_number_tree(_numbers.NUMBER_TREE)
    source = inspect.getsource(_numbers)
    assert "\n".join("#   " + line for line in lines) in source
    docs = (
        pathlib.Path(__file__).parents[3] / "docs/digests/digest_equivalence.rst"
    ).read_text()
    assert "\n".join("   " + line for line in lines) in docs




@pytest.mark.parametrize(
    "a, b",
    [
        (np.float64("nan"), float("nan")),
        (np.float32("nan"), float("nan")),
        (np.longdouble("nan"), float("nan")),
        (complex(math.nan, 0), math.nan),
    ],
)
def test_nans_with_the_same_bits_digest_equal_across_types(a, b):
    assert digest(a) == digest(b)


@pytest.mark.parametrize("nan", ["NaN", "-NaN", "sNaN", "NaN123"])
def test_decimal_nans_are_digestible(nan):
    # A signalling NaN raised ValueError from cmath.isnan (PR #990).
    assert digest(Decimal(nan)) == digest(Decimal(nan))
    assert digest(Decimal(nan)) != digest(float("nan"))


def test_decimal_nans_digest_apart():
    digests = {digest(Decimal(nan)) for nan in ["NaN", "-NaN", "sNaN", "NaN123"]}
    assert len(digests) == 4


def _unused(*args):
    raise NotImplementedError


class ExactReal(numbers_module.Real):
    """A foreign Real holding n/d exactly.

    It has only what numbers.Real promises: no __int__, no as_integer_ratio.
    """

    def __init__(self, n, d=1):
        self.q = Fraction(n, d)

    def __float__(self):
        return float(self.q)

    def __trunc__(self):
        return math.trunc(self.q)

    def __eq__(self, other):
        return self.q == other

    def __hash__(self):
        return hash(self.q)


for _name in numbers_module.Real.__abstractmethods__ - vars(ExactReal).keys():
    setattr(ExactReal, _name, _unused)
abc.update_abstractmethods(ExactReal)


@pytest.mark.filterwarnings("error")
def test_foreign_real_downcasts_without_int():
    # int() on it would delegate to __trunc__, deprecated and due to go.
    assert digest(ExactReal(2)) == digest(2)
    assert digest(ExactReal(1, 2)) == digest(0.5)


def test_foreign_real_beyond_float_without_ratio_is_indigestible():
    # Neither int nor float holds 1/3, and it offers no as_integer_ratio for
    # the Fraction node; that must end as Indigestible, not AttributeError.
    with pytest.raises(Indigestible):
        digest(ExactReal(1, 3))


@pytest.mark.parametrize(
    "value", [Fraction(10**400), Fraction(-(10**400), 7), [Fraction(2**1024)]]
)
def test_fraction_beyond_float_range_is_digestible(value):
    # The NaN check converted to float, which overflowed.
    digest(value)


def test_fraction_beyond_float_range_digests_as_its_value():
    assert digest(Fraction(10**400)) == digest(10**400)
    assert digest(Fraction(10**400)) == digest(Decimal("1e400"))


@pytest.mark.skipif(
    np.finfo(np.longdouble).maxexp < 16384, reason="np.longdouble cannot hold 1e4400 here"
)
@pytest.mark.parametrize("max_str_digits", [None, 0])
def test_huge_longdouble_digests_as_int_whatever_the_str_limit(max_str_digits):
    # numpy compares a longdouble with an int through str, so an int() == check
    # failed under the default sys.int_max_str_digits and passed without it.
    x = np.longdouble("1e4400")
    n = int(x)
    old = sys.get_int_max_str_digits()
    if max_str_digits is not None:
        sys.set_int_max_str_digits(max_str_digits)
    try:
        assert digest(x) == digest(n)
    finally:
        sys.set_int_max_str_digits(old)


def test_decimal_with_large_exponent_digests_quickly():
    # Taking it to int and back was quadratic: about 3.5 s for 1e300000.
    start = time.perf_counter()
    d = digest(Decimal("1e300000"))
    assert time.perf_counter() - start < 1
    assert d == digest(10**300000)


# What the digest promises equality against is the exact value, not == as
# numpy computes it: numpy casts a Python float down to float32 (NEP 50) and
# rounds a Fraction to double before comparing.
@pytest.mark.parametrize(
    "a, b, equal",
    [
        (np.float32(0.1), 0.1, False),
        (np.complex64(0.1 + 0.1j), complex(0.1, 0.1), False),
        (np.longdouble(1) / 3, Fraction(*(np.longdouble(1) / 3).as_integer_ratio()), True),
        (Decimal("Infinity"), np.longdouble("inf"), True),
        (complex(1.5, -0.0), 1.5, True),
    ],
)
def test_digest_follows_exact_value_not_numpy_equality(a, b, equal):
    assert (digest(a) == digest(b)) is equal


class MyInt(int):
    pass


class MyFloat(float):
    pass


class Colour(enum.IntEnum):
    RED = 1


def test_int_subclasses_keep_their_type_name_unlike_float_subclasses():
    # Pinned as observed: the int arm catches every int subclass and salts it
    # with its own name, like bool, while float subclasses downcast.
    assert digest(MyInt(5)) != digest(5)
    assert digest(Colour.RED) != digest(1)
    assert digest(MyFloat(5.0)) == digest(5)


def test_number_without_exact_value_is_indigestible():
    # Convertible to float, so it gets past the NaN check, but with no exact
    # value to offer: neither numerator/denominator nor as_integer_ratio.
    class Opaque(numbers_module.Number):
        def __float__(self):
            return 0.5

    with pytest.raises(Indigestible):
        digest(Opaque())


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
    if isinstance(value, np.ndarray) and value.dtype == object:
        out = np.empty(value.shape, dtype=object)
        for idx, v in np.ndenumerate(value):
            out[idx] = randomly_digest_subvalues(v, data)
        return out
    elif isinstance(value, list):
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


def test_numpy_object_array_digests_elements_not_pointers():
    """Regression (#1004): object arrays were digested via tobytes(), i.e. by
    PyObject address, so the digest changed per process and missed mutation."""
    import subprocess
    import sys

    code = (
        "import numpy as np; from fleche.digest import digest; "
        "print(digest(np.array(['abc', 12345, None, (1, 2)], dtype=object)))"
    )
    runs = {
        subprocess.run(
            [sys.executable, "-c", code], capture_output=True, text=True, check=True
        ).stdout
        for _ in range(2)
    }
    assert len(runs) == 1

    inner = [1]
    arr = np.array([None, inner], dtype=object)
    before = digest(arr)
    inner.append(2)
    assert digest(arr) != before

    # Equal contents in distinct objects digest the same.
    assert digest(np.array(["a" * 50, [1]], dtype=object)) == digest(
        np.array(["a" * 50, [1]], dtype=object)
    )


def test_numpy_object_array_of_arrays():
    """Object arrays holding arrays recurse into the ndarray arm, so a
    difference deep inside one element is seen."""
    a = np.empty(2, dtype=object)
    b = np.empty(2, dtype=object)
    big = np.arange(10_000)
    a[0], a[1] = big, np.zeros(3)
    b[0], b[1] = big.copy(), np.zeros(3)
    assert digest(a) == digest(b)
    b[0][5_000] = -1
    assert digest(a) != digest(b)


def test_numpy_object_array_shape_and_indigestible():
    a = np.array(["a", "b", "c", "d"], dtype=object)
    assert digest(a) != digest(a.reshape(2, 2))
    with pytest.raises(Indigestible):
        digest(np.array([object()], dtype=object))


def _object_array(elements, shape):
    # np.array(list_of_lists, dtype=object) would broadcast nested lists into
    # extra dimensions; assign element by element instead.
    out = np.empty(len(elements), dtype=object)
    for i, e in enumerate(elements):
        out[i] = e
    return out.reshape(shape)


@given(st.data())
def test_numpy_object_array_merkle_property(data):
    """Replacing any element (or sub-value of one) of an object array with its
    digest leaves the array digest unchanged."""
    elements = data.draw(st.lists(st_nested_values, min_size=1, max_size=6))
    shape = data.draw(st.sampled_from([(len(elements),), (1, len(elements))]))
    arr = _object_array(elements, shape)
    assert digest(randomly_digest_subvalues(arr, data)) == digest(arr)


@pytest.mark.parametrize(
    "value, partially_digested_value",
    (
        (
            _object_array(["a", [1, 2]], (2,)),
            _object_array(["a", digest([1, 2])], (2,)),
        ),
        (
            _object_array([Input(2), None, 3, "x"], (2, 2)),
            _object_array([digest(Input(2)), None, 3, digest("x")], (2, 2)),
        ),
        (
            # nested object array as an element, and inside a list
            _object_array([_object_array([[1], "b"], (2,)), 0], (2,)),
            _object_array([digest(_object_array([[1], "b"], (2,))), 0], (2,)),
        ),
        (
            [_object_array([np.arange(3), "b"], (2,))],
            [_object_array([digest(np.arange(3)), "b"], (2,))],
        ),
        (
            [_object_array([np.arange(3), "b"], (2,))],
            [digest(_object_array([np.arange(3), "b"], (2,)))],
        ),
        (
            np.array([(1, [2])], dtype=[("x", "i8"), ("y", "O")]),
            np.array([(1, digest([2]))], dtype=[("x", "i8"), ("y", "O")]),
        ),
    ),
)
def test_numpy_object_array_merkle_property_fixed(value, partially_digested_value):
    assert digest(value) == digest(partially_digested_value)


@pytest.mark.parametrize(
    "a, b",
    (
        # same itemsize and bytes, different field names / types / order
        (np.zeros(3, dtype=[("a", "i8"), ("b", "f8")]), np.zeros(3, dtype=[("x", "f8"), ("y", "i8")])),
        (np.array([(1,)], dtype=[("count", "i8")]), np.array([(1,)], dtype=[("price", "i8")])),
        (np.zeros(2, dtype=[("a", "i8")]), np.zeros(2, dtype=[("a", "f8")])),
        (np.zeros(2, dtype=[("a", "<i8")]), np.zeros(2, dtype=[("a", ">i8")])),
        (
            np.zeros(2, dtype=[("p", [("x", "f4"), ("y", "f4")])]),
            np.zeros(2, dtype=[("p", [("u", "f4"), ("v", "f4")])]),
        ),
    ),
)
def test_numpy_structured_dtypes_distinguished(a, b):
    """Regression: structured dtypes digested as dtype.str (``|V<itemsize>``),
    so field names, types and order were invisible."""
    assert a.tobytes() == b.tobytes()
    assert digest(a) != digest(b)


def test_numpy_structured_array_ignores_padding():
    """Padding bytes of aligned structured arrays are uninitialised; equal
    fields must digest equal regardless."""
    dt = np.dtype([("a", "u1"), ("b", "<i4")], align=True)
    x = np.empty(4, dtype=dt)
    y = np.zeros(4, dtype=dt)
    for arr in (x, y):
        arr["a"], arr["b"] = 1, 2
    x.view(np.uint8).reshape(4, 8)[:, 1:4] = 0xAB  # dirty the padding
    assert x.tobytes() != y.tobytes()
    assert digest(x) == digest(y)


def test_numpy_structured_array_with_object_field():
    dt = [("x", "i8"), ("y", "O")]
    inner = [1]
    s = np.array([(1, inner)], dtype=dt)
    before = digest(s)
    assert before == digest(np.array([(1, [1])], dtype=dt))
    inner.append(2)
    assert digest(s) != before


def test_pandas_dataframe_hashes_by_content():
    """Regression: DataFrame iter yields column names only, so falling through to
    the Iterable arm makes any two DataFrames with the same columns collide."""
    import pandas as pd

    df1 = pd.DataFrame({"a": [1, 2, 3], "b": [4, 5, 6]})
    df2 = pd.DataFrame({"a": [10, 20, 30], "b": [40, 50, 60]})
    df3 = pd.DataFrame({"a": [1, 2, 3], "b": [4, 5, 6]})

    assert digest(df1) != digest(df2)
    assert digest(df1) == digest(df3)
    assert isinstance(digest(df1), Digest)


def test_pandas_dataframe_distinguishes_columns_dtype_index():
    import pandas as pd

    base = pd.DataFrame({"a": [1, 2, 3], "b": [4, 5, 6]})
    reordered_cols = pd.DataFrame({"b": [4, 5, 6], "a": [1, 2, 3]})
    different_dtype = pd.DataFrame({"a": [1.0, 2.0, 3.0], "b": [4.0, 5.0, 6.0]})
    different_index = pd.DataFrame({"a": [1, 2, 3], "b": [4, 5, 6]}, index=[10, 20, 30])
    renamed_cols = pd.DataFrame({"a": [1, 2, 3], "c": [4, 5, 6]})

    digests = {digest(base), digest(reordered_cols), digest(different_dtype),
               digest(different_index), digest(renamed_cols)}
    assert len(digests) == 5


def test_pandas_series_hashes_by_content():
    import pandas as pd

    s1 = pd.Series([1, 2, 3])
    s2 = pd.Series([10, 20, 30])
    s3 = pd.Series([1, 2, 3])
    s_named = pd.Series([1, 2, 3], name="x")

    assert digest(s1) != digest(s2)
    assert digest(s1) == digest(s3)
    assert digest(s1) != digest(s_named)


def test_pandas_index_hashes_by_content():
    import pandas as pd

    i1 = pd.Index([1, 2, 3])
    i2 = pd.Index([1, 2, 4])
    i3 = pd.Index([1, 2, 3])
    i_named = pd.Index([1, 2, 3], name="x")

    assert digest(i1) != digest(i2)
    assert digest(i1) == digest(i3)
    assert digest(i1) != digest(i_named)


# The pandas containers whose arms digest object values element by element.
OBJECT_KINDS = ("series", "index", "frame")


def _pandas_of(kind, values):
    """Wrap *values* in the pandas container *kind*, so one test covers every arm.

    ``"series"`` and ``"index"`` hold *values* with object dtype, ``"frame"`` is a
    DataFrame whose single column does, and ``"categorical"`` is a Series of a
    Categorical over *values*, whose categories then have object dtype.
    """
    import pandas as pd

    match kind:
        case "series":
            return pd.Series(values, dtype=object)
        case "index":
            return pd.Index(values, dtype=object)
        case "frame":
            return pd.DataFrame({"c": pd.Series(values, dtype=object)})
        case "categorical":
            return pd.Series(pd.Categorical(values))
    raise ValueError(f"unknown pandas kind {kind!r}")


@pytest.mark.parametrize("kind", OBJECT_KINDS)
def test_pandas_object_column_of_arrays_digests_by_content(kind):
    """Issue #1004: pandas' default digester raised TypeError on a column of arrays.

    Now equal arrays give equal digests, and changing the values of one array
    changes the digest.
    """
    arrays = [np.zeros(3), np.ones(3)]
    changed = [np.zeros(3), np.full(3, 2.0)]

    assert digest(_pandas_of(kind, arrays)) == digest(_pandas_of(kind, [a.copy() for a in arrays]))
    assert digest(_pandas_of(kind, arrays)) != digest(_pandas_of(kind, changed))


def test_pandas_object_column_of_large_arrays_digests_all_elements():
    """Regression against pandas' default digester, which hashes objects through str().

    str() of a large array elides its middle, so a change there must still change
    the digest.
    """
    big = np.zeros(10_000)
    changed = big.copy()
    changed[5_000] = 1.0

    assert digest(_pandas_of("frame", [big])) != digest(_pandas_of("frame", [changed]))


@pytest.mark.parametrize("kind", OBJECT_KINDS)
@pytest.mark.parametrize(
    "values",
    [[[1, 2], [3]], [{"k": 1}, {"k": 2}], [{1, 2}, {3}]],
    ids=["lists", "dicts", "sets"],
)
def test_pandas_object_column_of_unhashables(kind, values):
    """Unhashable elements made pandas' default digester raise; they digest by content now.

    Equal values agree and the same values in another order differ.
    """
    assert digest(_pandas_of(kind, values)) == digest(_pandas_of(kind, values))
    assert digest(_pandas_of(kind, values)) != digest(_pandas_of(kind, values[::-1]))


@pytest.mark.parametrize("kind", OBJECT_KINDS + ("categorical",))
def test_pandas_mixed_object_values_do_not_collide_through_str(kind):
    """``1`` and ``"1"`` share a str(); pandas' default digester hashed both as ``"1"``."""
    assert digest(_pandas_of(kind, ["a", 1])) != digest(_pandas_of(kind, ["a", "1"]))
    assert digest(_pandas_of(kind, ["a", 1])) == digest(_pandas_of(kind, ["a", 1]))


def test_pandas_bytes_object_column_does_not_collide_with_str():
    """pandas' default digester hashed ``b"a"`` like ``"a"``."""
    assert digest(_pandas_of("series", [b"a"])) != digest(_pandas_of("series", ["a"]))


def test_pandas_object_column_with_pd_na():
    """``pd.NA`` digests stably, and differently from ``None``."""
    import pandas as pd

    assert digest(_pandas_of("series", [1, pd.NA])) == digest(_pandas_of("series", [1, pd.NA]))
    assert digest(_pandas_of("series", [1, pd.NA])) != digest(_pandas_of("series", [1, None]))


@pytest.mark.parametrize("kind", OBJECT_KINDS)
def test_pandas_object_column_of_unknown_objects_is_indigestible(kind):
    """Strict: pandas' default digester would key object() on its repr, i.e. its address."""
    with pytest.raises(Indigestible):
        digest(_pandas_of(kind, [object(), object()]))


@pytest.mark.parametrize("kind", OBJECT_KINDS)
def test_pandas_object_column_digests_like_the_column_of_its_digests(kind):
    """Merkle property, as for a list: replacing each element by its Digest keeps the digest."""
    arrays = [np.zeros(2), np.ones(2)]
    as_digests = [digest(a) for a in arrays]

    assert digest(arrays) == digest(as_digests)
    assert digest(_pandas_of(kind, arrays)) == digest(_pandas_of(kind, as_digests))


def test_pandas_dataframe_object_columns_with_repeated_labels():
    """Columns are swapped for their digests by position, so repeated labels still work."""
    import pandas as pd

    a = pd.DataFrame([[np.zeros(1), np.ones(1)]], columns=["c", "c"])
    b = pd.DataFrame([[np.ones(1), np.zeros(1)]], columns=["c", "c"])

    assert digest(a) != digest(b)


def test_pandas_dataframe_digest_leaves_the_frame_unchanged():
    """The digest columns go into a shallow copy, never into the frame passed in."""
    import pandas as pd

    arrays = [np.zeros(1), np.ones(1)]
    frame = pd.DataFrame([arrays], columns=["c", "d"])

    digest(frame)

    assert frame.iloc[0, 0] is arrays[0]
    assert frame.iloc[0, 1] is arrays[1]


def _multiindex(tuples, **kwargs):
    """A MultiIndex over *tuples*; *kwargs* go to ``MultiIndex.from_tuples``."""
    import pandas as pd

    return pd.MultiIndex.from_tuples(tuples, **kwargs)


def test_pandas_multiindex_object_level_does_not_collide_through_str():
    """pandas hashes a MultiIndex level by level, through str() for object levels."""
    a = _multiindex([("a", 1), ("b", "x")])
    b = _multiindex([("a", "1"), ("b", "x")])

    assert digest(a) != digest(b)
    assert digest(a) == digest(_multiindex([("a", 1), ("b", "x")]))


def test_pandas_multiindex_level_names_matter():
    """pandas ignores level names, and a MultiIndex's .name is None."""
    assert digest(_multiindex([("a", 1)], names=["p", "q"])) != digest(
        _multiindex([("a", 1)], names=["p", "r"])
    )


def test_pandas_multiindex_ignores_unused_level_entries():
    """Equal slices digest equal, whatever their ``.levels`` still hold from the full index."""
    full_a = _multiindex([("a", 1), ("b", 2)])
    full_b = _multiindex([("a", 1), ("c", 3)])

    assert digest(full_a[:1]) == digest(full_b[:1])


def test_pandas_multiindex_order_and_level_order_matter():
    """Reordering the rows, or swapping values between levels, changes the digest."""
    assert digest(_multiindex([("a", 1), ("b", 2)])) != digest(_multiindex([("b", 2), ("a", 1)]))
    assert digest(_multiindex([("a", "b")])) != digest(_multiindex([("b", "a")]))


def test_pandas_multiindex_of_unknown_objects_is_indigestible():
    """Strict, as for a flat Index: an object level of unknown objects raises."""
    with pytest.raises(Indigestible):
        digest(_multiindex([(object(), 1)]))


def test_pandas_dataframe_with_multiindex_rows():
    """A frame folds in its MultiIndex through the MultiIndex arm, object levels included."""
    import pandas as pd

    a = pd.DataFrame({"x": [1.0, 2.0]}, index=_multiindex([("a", 1), ("b", "x")]))
    b = pd.DataFrame({"x": [1.0, 2.0]}, index=_multiindex([("a", "1"), ("b", "x")]))

    assert digest(a) != digest(b)


def test_lambda_can_be_digested():
    """Test that lambda functions can be digested without raising Indigestible."""
    f = lambda x: x + 1
    result = digest(f)
    assert isinstance(result, Digest)


def test_locally_defined_function_can_be_digested():
    """Test that locally defined functions can be digested without raising Indigestible."""
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


# --- Functions: plain functions keep their historical wire format ---

def test_closure_free_function_digests_as_its_code_object():
    """Functions with neither captures nor defaults keep the historical wire format.

    Everything else is untouched by folding captured state in, so no cache built
    out of ordinary functions is invalidated.
    """
    def plain(x):
        return x + 1

    assert digest(plain) == digest(plain.__code__)


# --- Functions: captured free variables ---

def _adder(n):
    """Factory whose products share a code object and differ only in what they capture."""
    def add(x):
        return x + n
    return add


def test_closures_capturing_different_values_have_different_digests():
    """Two closures out of the same factory are told apart by what they captured.

    They share a code object, so a code-only digest gave them the same cache key
    while ``_adder(1)(0) != _adder(2)(0)``.
    """
    assert digest(_adder(1)) != digest(_adder(2))


def test_closures_capturing_equal_values_have_the_same_digest():
    """The digest stays content-based: equal captures, equal digest."""
    assert digest(_adder(1)) == digest(_adder(1))


def test_closure_over_mutated_capture_changes_digest():
    """Rebinding a captured variable changes the digest of the closure."""
    n = 1

    def capture():
        return n

    before = digest(capture)
    n = 2
    assert digest(capture) != before


def test_closure_with_unbound_free_variable_can_be_digested():
    """An empty cell (free variable never bound) has no value but is still digestible."""
    def outer():
        def inner():
            return never_assigned
        return inner
        never_assigned = 1  # unreachable, but it is what makes the name a cell

    inner = outer()
    with pytest.raises(ValueError):
        inner.__closure__[0].cell_contents

    assert isinstance(digest(inner), Digest)


def test_closure_over_indigestible_value_raises():
    """Captures follow the usual contract: what cannot be hashed is refused, not ignored."""
    class Opaque:
        pass

    def make(o):
        def f():
            return o
        return f

    with pytest.raises(Indigestible):
        digest(make(Opaque()))


# --- Functions: argument defaults ---

def test_functions_with_different_defaults_have_different_digests():
    """Argument defaults are part of what the function computes.

    They are evaluated once at definition time and share the code object, so a
    code-only digest gave ``lambda x, n=1`` and ``lambda x, n=2`` one cache key.
    """
    assert digest(lambda x, n=1: x + n) != digest(lambda x, n=2: x + n)


def test_functions_with_equal_defaults_have_the_same_digest():
    """Still content-based: equal defaults, equal digest."""
    assert digest(lambda x, n=1: x + n) == digest(lambda x, n=1: x + n)


def test_keyword_only_defaults_participate_in_the_digest():
    """``__kwdefaults__`` is a separate slot from ``__defaults__`` and counts too."""
    def one(x, *, n=1):
        return x + n

    def two(x, *, n=2):
        return x + n

    assert digest(one) != digest(two)


def test_late_bound_default_separates_closures_from_one_factory():
    """``k=n`` captures the enclosing value in a default rather than a cell.

    The idiom exists precisely to avoid late binding, so the two functions it
    produces differ in behaviour while sharing a code object *and* an empty
    closure.
    """
    def make(n):
        def scale(x, k=n):
            return x * k
        return scale

    assert digest(make(2)) != digest(make(3))


def test_mutated_default_changes_digest():
    """Defaults are read at digest time, so a mutable default moves the digest.

    The mutable-default idiom keeps state between calls; that state is part of
    what the next call computes, so the digest follows it.
    """
    def accumulate(x, acc=[]):
        acc.append(x)
        return acc

    before = digest(accumulate)
    accumulate(1)
    assert digest(accumulate) != before


def test_default_that_cannot_be_digested_raises():
    """Defaults follow the same contract as captures: refused, not ignored."""
    class Opaque:
        pass

    def f(x, o=Opaque()):
        return o

    with pytest.raises(Indigestible):
        digest(f)


# --- Functions: recursion and cycles in captured state ---

def _one_hop():
    """A function whose single free variable decides who it calls.

    Every instance shares one code object, so the *only* thing that can tell two
    of them apart is the shape of the call graph their cells describe.
    """
    def f():
        return partner()

    partner = None
    return f


def test_self_recursive_closure_can_be_digested():
    """A recursive inner function captures *itself*; digesting must terminate."""
    def make(k):
        def countdown(n):
            return countdown(n - 1) + k if n else 0
        return countdown

    assert isinstance(digest(make(1)), Digest)
    # the cycle is broken by a placeholder, but the other capture still discriminates
    assert digest(make(1)) != digest(make(2))


def test_mutually_recursive_closures_can_be_digested():
    """Two closures capturing each other must not recurse forever either."""
    def make(k):
        def even(n):
            return odd(n)

        def odd(n):
            return even(n) + k
        return even

    assert isinstance(digest(make(1)), Digest)
    assert digest(make(1)) != digest(make(2))


def test_self_referential_default_can_be_digested():
    """A function reachable from its own defaults must not recurse forever."""
    def f(x):
        return x

    f.__defaults__ = (f,)
    assert isinstance(digest(f), Digest)


def test_cycles_of_equal_length_closing_on_different_functions_differ():
    """A constant cycle marker would collide two different call graphs.

    ``a -> b -> a`` (mutual ping-pong) and ``c -> d -> d`` (one hop, then self
    recursion) run to the same depth through identical code objects, so a marker
    that says only "seen this already" hashes them the same.  The marker names
    how far back up the walk the target sits instead.
    """
    a, b, c, d = _one_hop(), _one_hop(), _one_hop(), _one_hop()
    a.__closure__[0].cell_contents = b
    b.__closure__[0].cell_contents = a
    c.__closure__[0].cell_contents = d
    d.__closure__[0].cell_contents = d

    assert a.__code__ is c.__code__     # nothing but the cycle shape differs
    assert digest(a) != digest(c)


def test_equivalent_cycles_still_agree():
    """Discriminating cycle shape must not cost content-based equality."""
    a, b = _one_hop(), _one_hop()
    a.__closure__[0].cell_contents = b
    b.__closure__[0].cell_contents = a

    c, d = _one_hop(), _one_hop()
    c.__closure__[0].cell_contents = d
    d.__closure__[0].cell_contents = c

    assert digest(a) == digest(c)


def test_cycle_digests_the_same_wherever_it_is_met():
    """The back-reference is relative, so a cycle is context-independent.

    An absolute depth would make the same cycle hash differently depending on
    how deeply the walk had already descended when it reached it.
    """
    a, b = _one_hop(), _one_hop()
    a.__closure__[0].cell_contents = b
    b.__closure__[0].cell_contents = a

    def hold(x):
        def h():
            return x()
        return h

    standalone = digest(a)
    nested = digest(hold(a))
    assert nested != standalone         # h wraps it, so of course it differs
    # but two copies of the same cycle agree at the same nesting
    c, d = _one_hop(), _one_hop()
    c.__closure__[0].cell_contents = d
    d.__closure__[0].cell_contents = c
    assert digest(hold(c)) == nested


# --- Functions: compiler-inserted cells and per-instance identity ---

def test_method_using_super_can_be_digested():
    """The compiler-inserted ``__class__`` cell must not make methods indigestible.

    Any method mentioning ``super()`` captures its class in a cell, and a
    user-defined class is :exc:`Indigestible` as a *value* — so digesting the
    cell would refuse every such method.  It is identified by name instead.
    """
    class Base:
        def go(self):
            return 1

    class A(Base):
        def go(self):
            return super().go() + 1

    class B(Base):
        def go(self):
            return super().go() + 1

    a, b = A.__dict__["go"], B.__dict__["go"]
    assert a.__code__.co_freevars == ("__class__",)
    # identical bodies, but the classes they were defined in differ
    assert digest(a) != digest(b)


def test_function_digest_attribute_overrides_closure_digest():
    """``__digest__`` is honoured per instance for functions.

    Every function shares one type, so the class-level protocol could never
    reach them; the attribute is how a closure declares its own identity.
    """
    def make(o):
        def f():
            return o
        return f

    f = make(object())
    f.__digest__ = lambda: digest("stable identity")
    assert digest(f) == digest("stable identity")


# --- Bound methods: digest() covers them like any other value ---

@dataclass
class _Counter:
    """A digestible receiver, so the method's own digest can be exercised."""

    start: int

    def advance(self, by):
        return self.start + by


def test_bound_methods_of_different_receivers_differ():
    """The receiver is part of what the method computes.

    Leaving ``__self__`` out would collide ``obj1.method`` with ``obj2.method``,
    the same shape of bug as digesting a closure by its code alone.
    """
    assert digest(_Counter(1).advance) != digest(_Counter(2).advance)


def test_bound_methods_of_equal_receivers_agree():
    """Still content-based: equal receivers, equal digest."""
    assert digest(_Counter(1).advance) == digest(_Counter(1).advance)


def test_bound_method_differs_from_its_underlying_function():
    """Binding is not transparent — the bound method carries a receiver."""
    assert digest(_Counter(1).advance) != digest(_Counter.advance)


def test_bound_classmethod_receiver_is_named_not_valued():
    """A classmethod's receiver is a class, which is Indigestible as a value.

    It is identified by qualified name instead, exactly as the ``__class__``
    cell of a ``super()``-using method is.
    """

    class A:
        @classmethod
        def make(cls):
            return cls

    assert isinstance(digest(A.make), Digest)


def test_bound_method_of_indigestible_receiver_raises():
    """A bound method is no more digestible than the object it is bound to."""

    class Opaque:
        def go(self):
            return 1

    with pytest.raises(Indigestible):
        digest(Opaque().go)

# --- Tests for digesting Python descriptors (staticmethod, classmethod, property) ---
#
# As with the datetime block, plain "X is digestible" smokes are omitted: each
# test here digests real descriptors, so losing descriptor support fails them.


def test_staticmethod_digest_differs_from_underlying_function_digest():
    """digest(staticmethod(f)) != digest(f) — type salting keeps them distinct."""

    def func(x):
        return x * 2

    assert digest(staticmethod(func)) != digest(func)


def test_classmethod_digest_differs_from_underlying_function_digest():
    """digest(classmethod(f)) != digest(f) — type salting keeps them distinct."""

    def func(cls, x):
        return x * 2

    assert digest(classmethod(func)) != digest(func)


def test_staticmethod_and_classmethod_differ():
    """Same underlying function wrapped as staticmethod vs classmethod must produce different digests."""

    def func(x):
        return x

    assert digest(staticmethod(func)) != digest(classmethod(func))


def test_staticmethods_with_different_bodies_have_different_digests():
    """Two staticmethods wrapping different functions must produce different digests."""

    def f(x):
        return x + 1

    def g(x):
        return x + 2

    assert digest(staticmethod(f)) != digest(staticmethod(g))


def test_classmethods_with_different_bodies_have_different_digests():
    """Two classmethods wrapping different functions must produce different digests."""

    def f(cls, x):
        return x + 1

    def g(cls, x):
        return x + 2

    assert digest(classmethod(f)) != digest(classmethod(g))


def test_property_with_only_getter():
    """A property with only a getter must be digestible."""

    def getter(self):
        return self._value

    p = property(getter)
    result = digest(p)
    assert isinstance(result, Digest)


def test_property_with_getter_and_setter():
    """A property with getter and setter must be digestible."""

    def getter(self):
        return self._value

    def setter(self, v):
        self._value = v

    p = property(getter, setter)
    result = digest(p)
    assert isinstance(result, Digest)


def test_property_with_getter_setter_deleter():
    """A property with getter, setter, and deleter must be digestible."""

    def getter(self):
        return self._value

    def setter(self, v):
        self._value = v

    def deleter(self):
        del self._value

    p = property(getter, setter, deleter)
    result = digest(p)
    assert isinstance(result, Digest)


def test_properties_with_different_getters_have_different_digests():
    """Two properties with different getter functions must produce different digests."""

    def getter_a(self):
        return self._a

    def getter_b(self):
        return self._b

    assert digest(property(getter_a)) != digest(property(getter_b))


def test_property_none_setter_vs_setter_differ():
    """Adding a setter to a property changes its digest."""

    def getter(self):
        return self._value

    def setter(self, v):
        self._value = v

    assert digest(property(getter)) != digest(property(getter, setter))


def test_property_digest_differs_from_tuple():
    """property has-a triple of functions but is-not a tuple — digests must differ."""

    def getter(self):
        return self._value

    def setter(self, v):
        self._value = v

    def deleter(self):
        del self._value

    p = property(getter, setter, deleter)
    assert digest(p) != digest((getter, setter, deleter))


class _CustomMapping(collections.abc.Mapping):
    """Minimal Mapping implementation (not a dict subclass)."""
    def __init__(self, d):
        self._d = dict(d)

    def __getitem__(self, key):
        return self._d[key]

    def __iter__(self):
        return iter(self._d)

    def __len__(self):
        return len(self._d)


def test_generic_mapping_value_change_causes_digest_change():
    """Changing a value in a non-dict Mapping must change its digest."""
    cm1 = collections.ChainMap({'a': 1, 'b': 2})
    cm2 = collections.ChainMap({'a': 99, 'b': 2})
    assert digest(cm1) != digest(cm2)

    m1 = _CustomMapping({'x': 'hello'})
    m2 = _CustomMapping({'x': 'world'})
    assert digest(m1) != digest(m2)


def test_generic_mapping_key_change_causes_digest_change():
    """Changing a key in a non-dict Mapping must change its digest."""
    m1 = _CustomMapping({'a': 1})
    m2 = _CustomMapping({'b': 1})
    assert digest(m1) != digest(m2)


def test_different_mapping_types_same_content_hash_differently():
    """Different mapping types with identical content must hash differently."""
    content = {'a': 1, 'b': 2}

    d = dict(content)
    cm = collections.ChainMap(content)
    m = _CustomMapping(content)
    od = collections.OrderedDict(content)

    # plain dict vs ChainMap
    assert digest(d) != digest(cm)
    # plain dict vs custom Mapping
    assert digest(d) != digest(m)
    # plain dict vs OrderedDict (already handled by dict case, but type name differs)
    assert digest(d) != digest(od)
    # ChainMap vs custom Mapping
    assert digest(cm) != digest(m)


def test_generic_mapping_same_content_same_type_identical_digest():
    """Two Mapping instances of the same type with the same content must hash identically."""
    m1 = _CustomMapping({'a': 1, 'b': 2})
    m2 = _CustomMapping({'b': 2, 'a': 1})  # insertion order differs
    assert digest(m1) == digest(m2)

    cm1 = collections.ChainMap({'a': 1}, {'b': 2})
    cm2 = collections.ChainMap({'b': 2, 'a': 1})
    assert digest(cm1) == digest(cm2)


# --- Tests for datetime type digests ---
#
# Digestibility of each type is pinned transitively: every test below digests
# real instances, so a regression that made one of these types Indigestible
# fails here.  Dedicated "X is digestible" smokes would be strictly weaker.


def test_different_dates_have_different_digests():
    assert digest(datetime.date(2024, 1, 1)) != digest(datetime.date(2024, 1, 2))
    assert digest(datetime.date(2024, 1, 1)) != digest(datetime.date(2025, 1, 1))


def test_different_datetimes_have_different_digests():
    assert digest(datetime.datetime(2024, 1, 1, 0, 0)) != digest(datetime.datetime(2024, 1, 1, 0, 1))
    assert digest(datetime.datetime(2024, 1, 1, 0, 0)) != digest(datetime.datetime(2024, 1, 2, 0, 0))


def test_different_times_have_different_digests():
    assert digest(datetime.time(12, 0, 0)) != digest(datetime.time(12, 0, 1))
    assert digest(datetime.time(12, 0, 0)) != digest(datetime.time(13, 0, 0))


def test_different_timezones_have_different_digests():
    tz_utc = datetime.timezone.utc
    tz_plus5 = datetime.timezone(datetime.timedelta(hours=5))
    tz_minus3 = datetime.timezone(datetime.timedelta(hours=-3))
    assert digest(tz_utc) != digest(tz_plus5)
    assert digest(tz_plus5) != digest(tz_minus3)
    tz_plus5_us = datetime.timezone(datetime.timedelta(hours=5, microseconds=1))
    assert digest(tz_plus5) != digest(tz_plus5_us)
    # timezone == compares the offset only, so the name must not split them.
    assert digest(tz_plus5) == digest(datetime.timezone(datetime.timedelta(hours=5), "X"))


def test_datetime_subclass_matches_before_date():
    """datetime.datetime is a subclass of datetime.date; they must produce different digests."""
    d = datetime.date(2024, 6, 15)
    dt = datetime.datetime(2024, 6, 15, 0, 0, 0)
    assert digest(d) != digest(dt)


def test_datetime_same_value_same_digest():
    assert digest(datetime.date(2024, 3, 10)) == digest(datetime.date(2024, 3, 10))
    assert digest(datetime.datetime(2024, 3, 10, 8, 0)) == digest(datetime.datetime(2024, 3, 10, 8, 0))
    assert digest(datetime.time(8, 30)) == digest(datetime.time(8, 30))
    assert digest(datetime.timezone.utc) == digest(datetime.timezone.utc)


def test_datetime_timezone_aware_differs_from_naive():
    """A timezone-aware datetime digests differently from a naive one with the same wall-clock values."""
    naive = datetime.datetime(2024, 1, 1, 12, 0)
    aware = datetime.datetime(2024, 1, 1, 12, 0, tzinfo=datetime.timezone.utc)
    assert digest(naive) != digest(aware)


def test_datetime_stdlib_class_constants_digestible():
    """Motivating use case: stdlib class-level datetime constants (e.g. date.min) must be digestible.

    This is needed so that digest(dict(datetime.date.__dict__)) can eventually work.
    """
    assert digest(datetime.date.min) is not None
    assert digest(datetime.date.max) is not None
    assert digest(datetime.datetime.min) is not None
    assert digest(datetime.datetime.max) is not None
    assert digest(datetime.time.min) is not None
    assert digest(datetime.time.max) is not None
    assert digest(datetime.timezone.utc) is not None


# --- module digest tests ---


def _make_module(name="test_mod", **attrs):
    """Helper: create a ModuleType and set given attrs."""
    m = types_module.ModuleType(name)
    for k, v in attrs.items():
        setattr(m, k, v)
    return m


def test_module_digest_is_stable():
    """Digesting the same module object twice returns the same digest."""
    m = _make_module(x=1, y="hello")
    assert digest(m) == digest(m)


def test_module_digest_uses_all_when_present():
    """When __all__ is defined only those names affect the digest."""
    m1 = _make_module(x=1, y=2, z=3)
    m1.__all__ = ["x", "y"]

    # m2 has a different z but same __all__ exports
    m2 = _make_module(x=1, y=2, z=999)
    m2.__all__ = ["x", "y"]

    assert digest(m1) == digest(m2)


def test_module_digest_all_restricts_to_exported_names():
    """Adding an attribute not in __all__ does not change the digest."""
    m = _make_module(x=1)
    m.__all__ = ["x"]
    d_before = digest(m)

    m.secret = 42  # not in __all__
    d_after = digest(m)

    assert d_before == d_after


def test_module_digest_all_change_changes_digest():
    """Changing an exported attribute value changes the digest."""
    m1 = _make_module(x=1)
    m1.__all__ = ["x"]

    m2 = _make_module(x=2)
    m2.__all__ = ["x"]

    assert digest(m1) != digest(m2)


def test_module_digest_uses_dir_when_no_all():
    """Without __all__, two modules with different attribute values differ."""
    m1 = _make_module(x=1, y=2)
    m2 = _make_module(x=1, y=3)

    assert digest(m1) != digest(m2)


def test_module_digest_adding_attribute_changes_digest():
    """Adding a new attribute (no __all__) changes the digest."""
    m = _make_module(x=1)
    d1 = digest(m)

    m.y = 2
    d2 = digest(m)

    assert d1 != d2



def test_module_digest_with_function_attribute():
    """Modules containing Python functions are digestible."""
    def my_func(x):
        return x + 1

    m = _make_module()
    m.my_func = my_func
    m.__all__ = ["my_func"]

    assert isinstance(digest(m), Digest)


def test_module_digest_function_content_independence():
    """Two modules with __all__-exported functions with identical bodies hash the same."""
    def f1(x):
        return x + 1

    def f2(x):
        return x + 1

    m1 = _make_module()
    m1.func = f1
    m1.__all__ = ["func"]

    m2 = _make_module()
    m2.func = f2
    m2.__all__ = ["func"]

    assert digest(m1) == digest(m2)


# --- Tests for the Indigestible boundary of type objects — issue #469 ---
#
# Digestibility, stability, and distinctness of built-in type objects are covered
# by ``test_supported_types`` / ``test_supported_values_digest_stably`` /
# ``test_supported_values_digest_distinctly`` (BUILTIN_TYPES are folded into
# SUPPORTED_VALUES).  Only the negative boundary needs a dedicated test: anything
# outside the ``builtins`` module — including dataclass *classes* — must raise.


@dataclass
class _Pt:
    x: int


@pytest.mark.parametrize("t", [type("MyClass", (), {}), _Pt])
def test_non_builtin_type_raises_indigestible(t):
    """Non-builtin type objects (user-defined classes, dataclass classes) raise Indigestible."""
    with pytest.raises(Indigestible):
        digest(t)
