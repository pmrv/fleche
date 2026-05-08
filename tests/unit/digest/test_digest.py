import cmath
import datetime
import struct
import collections
import collections.abc
import types as types_module

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


# --- Tests for digesting Python descriptors (staticmethod, classmethod, property) ---


def test_staticmethod_can_be_digested():
    """staticmethod objects must be digestible without raising Unhashable."""

    def func(x):
        return x + 1

    sm = staticmethod(func)
    result = digest(sm)
    assert isinstance(result, Digest)


def test_classmethod_can_be_digested():
    """classmethod objects must be digestible without raising Unhashable."""

    def func(cls, x):
        return x + 1

    cm = classmethod(func)
    result = digest(cm)
    assert isinstance(result, Digest)


def test_property_can_be_digested():
    """property objects must be digestible without raising Unhashable."""

    def getter(self):
        return self._x

    p = property(getter)
    result = digest(p)
    assert isinstance(result, Digest)


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


def test_datetime_date_is_digestible():
    assert digest(datetime.date(2024, 1, 15)) is not None


def test_datetime_datetime_is_digestible():
    assert digest(datetime.datetime(2024, 1, 15, 12, 0, 0)) is not None


def test_datetime_time_is_digestible():
    assert digest(datetime.time(12, 30, 45)) is not None


def test_datetime_timedelta_is_digestible():
    assert digest(datetime.timedelta(days=3, seconds=7200)) is not None


def test_datetime_timezone_is_digestible():
    assert digest(datetime.timezone.utc) is not None
    assert digest(datetime.timezone(datetime.timedelta(hours=5))) is not None


def test_different_dates_have_different_digests():
    assert digest(datetime.date(2024, 1, 1)) != digest(datetime.date(2024, 1, 2))
    assert digest(datetime.date(2024, 1, 1)) != digest(datetime.date(2025, 1, 1))


def test_different_datetimes_have_different_digests():
    assert digest(datetime.datetime(2024, 1, 1, 0, 0)) != digest(datetime.datetime(2024, 1, 1, 0, 1))
    assert digest(datetime.datetime(2024, 1, 1, 0, 0)) != digest(datetime.datetime(2024, 1, 2, 0, 0))


def test_different_times_have_different_digests():
    assert digest(datetime.time(12, 0, 0)) != digest(datetime.time(12, 0, 1))
    assert digest(datetime.time(12, 0, 0)) != digest(datetime.time(13, 0, 0))


def test_different_timedeltas_have_different_digests():
    assert digest(datetime.timedelta(days=1)) != digest(datetime.timedelta(days=2))
    assert digest(datetime.timedelta(seconds=1)) != digest(datetime.timedelta(seconds=2))


def test_different_timezones_have_different_digests():
    tz_utc = datetime.timezone.utc
    tz_plus5 = datetime.timezone(datetime.timedelta(hours=5))
    tz_minus3 = datetime.timezone(datetime.timedelta(hours=-3))
    assert digest(tz_utc) != digest(tz_plus5)
    assert digest(tz_plus5) != digest(tz_minus3)


def test_datetime_subclass_matches_before_date():
    """datetime.datetime is a subclass of datetime.date; they must produce different digests."""
    d = datetime.date(2024, 6, 15)
    dt = datetime.datetime(2024, 6, 15, 0, 0, 0)
    assert digest(d) != digest(dt)


def test_datetime_same_value_same_digest():
    assert digest(datetime.date(2024, 3, 10)) == digest(datetime.date(2024, 3, 10))
    assert digest(datetime.datetime(2024, 3, 10, 8, 0)) == digest(datetime.datetime(2024, 3, 10, 8, 0))
    assert digest(datetime.time(8, 30)) == digest(datetime.time(8, 30))
    assert digest(datetime.timedelta(hours=2)) == digest(datetime.timedelta(hours=2))
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
    assert digest(datetime.date.resolution) is not None
    assert digest(datetime.datetime.min) is not None
    assert digest(datetime.datetime.max) is not None
    assert digest(datetime.time.min) is not None
    assert digest(datetime.time.max) is not None
    assert digest(datetime.timedelta.min) is not None
    assert digest(datetime.timedelta.max) is not None
    assert digest(datetime.timedelta.resolution) is not None
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


# --- Tests for digesting types (classes themselves, not instances) ---


def test_plain_class_type_can_be_digested():
    """Digesting a plain class must not raise."""
    class Foo:
        pass

    assert isinstance(digest(Foo), Digest)


def test_builtin_types_can_be_digested():
    """Built-in types like int, str, list must be digestible."""
    for t in (int, str, float, bool, list, dict, tuple, bytes, type(None)):
        result = digest(t)
        assert isinstance(result, Digest), f"digest({t}) did not return a Digest"


def test_dataclass_type_can_be_digested():
    """Digesting a dataclass class (not an instance) must not raise."""
    @dataclass
    class MyData:
        x: int
        y: str

    assert isinstance(digest(MyData), Digest)


def test_dataclass_type_digest_differs_from_instance_digest():
    """The digest of a dataclass class must differ from any of its instances."""
    @dataclass
    class Point:
        x: int = 0
        y: int = 0

    assert digest(Point) != digest(Point(x=0, y=0))


def test_same_type_always_produces_same_digest():
    """Digesting the same type multiple times must return the same value."""
    class Stable:
        x: int = 1

    assert digest(Stable) == digest(Stable)


def test_type_digest_reflects_added_attribute():
    """Adding a class attribute changes the type digest."""
    class WithoutAttr:
        pass

    class WithAttr:
        extra = 42

    assert digest(WithAttr) != digest(WithoutAttr)


def test_type_digest_reflects_attribute_value():
    """Changing a class attribute value changes the type digest."""
    class A:
        x = 1

    class B:
        x = 999

    assert digest(A) != digest(B)


def test_type_digest_reflects_method_presence():
    """Adding a method changes the type digest."""
    class WithoutMethod:
        pass

    class WithMethod:
        def compute(self):
            return 1

    assert digest(WithMethod) != digest(WithoutMethod)


def test_type_digest_different_names_differ():
    """Two classes with the same structure but different names produce different digests.

    Each class's __dict__ contains __dict__ and __weakref__ descriptors whose
    __qualname__ encodes the class name, so name differences propagate to the digest.
    """
    class ClassA:
        x = 1

    class ClassB:
        x = 1

    assert digest(ClassA) != digest(ClassB)


def test_type_digest_equals_digest_of_dict():
    """digest(T) == digest(dict(T.__dict__)) for a plain user-defined class."""
    from fleche.digest import _digest_bytes

    class MyClass:
        x = 1
        def method(self): return self.x

    assert digest(MyClass) == digest(dict(MyClass.__dict__))


def test_builtin_type_digest_equals_digest_of_dict():
    """digest(int) == digest(dict(int.__dict__)) — strict equivalence holds for stdlib types."""
    assert digest(int) == digest(dict(int.__dict__))


def test_D_on_dataclass_type():
    """fl.D(C) where C is a dataclass type must work (regression for issue #469)."""
    from fleche import D

    @dataclass
    class Config:
        n: int
        label: str

    assert isinstance(D(Config), Digest)


def test_c_descriptor_digestible():
    """C-level descriptor types (wrapper_descriptor, method_descriptor, etc.) must be digestible."""
    assert isinstance(digest(int.__add__), Digest)        # wrapper_descriptor
    assert isinstance(digest(str.upper), Digest)          # method_descriptor
    assert isinstance(digest(int.from_bytes), Digest)     # classmethod_descriptor
    assert isinstance(digest(len), Digest)                # builtin_function_or_method


def test_c_descriptor_qualname_stability():
    """The same C descriptor always produces the same digest."""
    assert digest(int.__add__) == digest(int.__add__)
    assert digest(str.upper) == digest(str.upper)


def test_c_descriptor_different_qualnames_differ():
    """Two different C descriptors with different qualnames produce different digests."""
    assert digest(int.__add__) != digest(int.__mul__)
    assert digest(str.upper) != digest(str.lower)


def test_type_digest_stable_across_dill_roundtrip():
    """A transient class has the same digest after a dill round-trip."""
    import dill

    def make_class():
        class LocalClass:
            x = 1
            def method(self): return self.x
        return LocalClass

    cls = make_class()
    original = digest(cls)
    reloaded = dill.loads(dill.dumps(cls))
    assert digest(reloaded) == original


def test_type_digest_stable_across_cloudpickle_roundtrip():
    """A transient class has the same digest after a cloudpickle round-trip."""
    import cloudpickle

    def make_class():
        class LocalClass:
            y = "hello"
            def double(self, v): return v * 2
        return LocalClass

    cls = make_class()
    original = digest(cls)
    reloaded = cloudpickle.loads(cloudpickle.dumps(cls))
    assert digest(reloaded) == original


# --- Tests for dataclasses._FIELD_BASE (Python 3.12: _FIELD / _FIELD_CLASSVAR / _FIELD_INITVAR) ---


def test_field_base_singletons_are_digestible():
    """The three _FIELD_BASE singletons must be digestible."""
    import dataclasses as dc
    assert isinstance(digest(dc._FIELD), Digest)
    assert isinstance(digest(dc._FIELD_CLASSVAR), Digest)
    assert isinstance(digest(dc._FIELD_INITVAR), Digest)


def test_field_base_singletons_have_distinct_digests():
    """The three singletons must produce different digests."""
    import dataclasses as dc
    assert digest(dc._FIELD) != digest(dc._FIELD_CLASSVAR)
    assert digest(dc._FIELD) != digest(dc._FIELD_INITVAR)
    assert digest(dc._FIELD_CLASSVAR) != digest(dc._FIELD_INITVAR)


def test_field_base_digest_is_stable():
    """Digesting the same singleton twice returns the same value."""
    import dataclasses as dc
    assert digest(dc._FIELD) == digest(dc._FIELD)
    assert digest(dc._FIELD_CLASSVAR) == digest(dc._FIELD_CLASSVAR)


def test_field_instance_is_digestible():
    """A dataclasses.Field instance (which carries _field_type) must be digestible."""
    import dataclasses as dc

    @dataclass
    class Simple:
        x: int = 0

    field_obj = dc.fields(Simple)[0]
    assert isinstance(digest(field_obj), Digest)


def test_field_instance_digest_changes_with_value():
    """Two Field instances for different field names must differ."""
    import dataclasses as dc

    @dataclass
    class TwoFields:
        a: int = 1
        b: str = "hi"

    fa, fb = dc.fields(TwoFields)
    assert digest(fa) != digest(fb)
