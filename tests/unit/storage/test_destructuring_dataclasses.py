"""Tests for DigestedDataclass support in DestructuringMixin.

Covers the full range of dataclass shapes: plain, frozen, init=False fields,
InitVar fields, combinations thereof, nested structures, and edge cases.
"""
import pytest
from collections import namedtuple
from dataclasses import dataclass, field, InitVar, fields as dc_fields
from hypothesis import given, settings, HealthCheck, strategies as st

from fleche.storage import ValueMixin, DestructuringMixin
from fleche.storage.memory import MemoryBackend
from fleche.storage.destructuring import DigestedDataclass, Digested
from fleche.digest import digest, Digest

from tests.strategies import st_base_values, st_nested_values, dataclasses as st_dataclasses


# ---------------------------------------------------------------------------
# Test fixture storage class
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class DestructuringMemory(DestructuringMixin, ValueMixin, MemoryBackend):
    __hash__ = object.__hash__


@pytest.fixture
def ds():
    return DestructuringMemory(storage={})


def make_ds(remaining_depth=0):
    return DestructuringMemory(storage={}, remaining_depth=remaining_depth)


# ---------------------------------------------------------------------------
# Dataclass shapes used throughout the tests
# ---------------------------------------------------------------------------

@dataclass
class Basic:
    x: int
    y: str


@dataclass(frozen=True)
class Frozen:
    x: int
    y: list


@dataclass
class WithInitFalse:
    x: int
    y: int = field(init=False)

    def __post_init__(self):
        self.y = self.x * 2


@dataclass
class WithInitVar:
    x: int
    z: int = field(init=False)
    y: InitVar[int] = 0

    def __post_init__(self, y: int):
        self.z = self.x + y


@dataclass
class WithInitVarAndInitFalse:
    base: int
    multiplier: InitVar[int] = 1
    scaled: int = field(init=False)
    shifted: int = field(init=False)

    def __post_init__(self, multiplier: int):
        self.scaled = self.base * multiplier
        self.shifted = self.base + multiplier


@dataclass
class EmptyDC:
    pass


@dataclass
class Nested:
    items: list
    meta: dict


@dataclass
class DCwithDC:
    inner: Basic
    tag: str


@dataclass
class FrozenNested:
    name: str
    data: list

    def __hash__(self):
        return hash((self.name, tuple(self.data)))


# ---------------------------------------------------------------------------
# Basic roundtrip
# ---------------------------------------------------------------------------

def test_basic_roundtrip(ds):
    b = Basic(x=42, y="hello")
    key = ds.save(b)
    loaded = ds.load(key)
    assert loaded == b
    assert type(loaded) is Basic


def test_frozen_roundtrip(ds):
    f = Frozen(x=1, y=[2, 3, 4])
    key = ds.save(f)
    loaded = ds.load(key)
    assert loaded == f
    assert type(loaded) is Frozen


def test_init_false_roundtrip(ds):
    obj = WithInitFalse(x=5)
    assert obj.y == 10
    key = ds.save(obj)
    loaded = ds.load(key)
    assert loaded.x == 5
    assert loaded.y == 10
    assert type(loaded) is WithInitFalse


def test_initvar_roundtrip(ds):
    """InitVar 'y' is consumed by __post_init__ and never stored as an attribute."""
    obj = WithInitVar(x=3, y=7)
    assert obj.z == 10  # x + y
    key = ds.save(obj)
    loaded = ds.load(key)
    assert loaded.x == 3
    assert loaded.z == 10
    assert type(loaded) is WithInitVar


def test_initvar_and_init_false_roundtrip(ds):
    obj = WithInitVarAndInitFalse(base=4, multiplier=3)
    assert obj.scaled == 12
    assert obj.shifted == 7
    key = ds.save(obj)
    loaded = ds.load(key)
    assert loaded.base == 4
    assert loaded.scaled == 12
    assert loaded.shifted == 7
    assert type(loaded) is WithInitVarAndInitFalse


def test_empty_dataclass_roundtrip(ds):
    e = EmptyDC()
    key = ds.save(e)
    loaded = ds.load(key)
    assert type(loaded) is EmptyDC


def test_nested_fields_roundtrip(ds):
    obj = Nested(items=[1, 2, 3], meta={"a": 1})
    key = ds.save(obj)
    loaded = ds.load(key)
    assert loaded == obj
    assert type(loaded) is Nested


def test_dataclass_containing_dataclass_roundtrip(ds):
    inner = Basic(x=1, y="inner")
    outer = DCwithDC(inner=inner, tag="outer")
    key = ds.save(outer)
    loaded = ds.load(key)
    assert loaded == outer
    assert type(loaded) is DCwithDC
    assert type(loaded.inner) is Basic


# ---------------------------------------------------------------------------
# Storage structure tests: assert a DigestedDataclass is created
# ---------------------------------------------------------------------------

def test_basic_stored_as_digested_dataclass(ds):
    b = Basic(x=1, y="hello")
    key = ds.save(b)
    raw = ds.storage[key]
    assert isinstance(raw, DigestedDataclass)
    assert raw.cls is Basic


def test_frozen_stored_as_digested_dataclass(ds):
    f = Frozen(x=0, y=[])
    key = ds.save(Frozen(x=1, y=[2]))
    raw = ds.storage[key]
    assert isinstance(raw, DigestedDataclass)


def test_empty_dataclass_not_stored_as_digested(ds):
    """Empty dataclasses have no fields to destructure; stored as plain objects."""
    e = EmptyDC()
    key = ds.save(e)
    raw = ds.storage[key]
    assert not isinstance(raw, DigestedDataclass)


def test_field_values_stored_separately(ds):
    """Each field value of a dataclass gets its own storage slot at remaining_depth=0."""
    b = Basic(x=99, y="world")
    key = ds.save(b)
    raw = ds.storage[key]
    assert isinstance(raw, DigestedDataclass)
    # Field values themselves must be stored as separate Digest references.
    assert all(isinstance(v, Digest) for v in raw.fields.values())


# ---------------------------------------------------------------------------
# Digest transparency: DigestedDataclass must hash like the original instance
# ---------------------------------------------------------------------------

def test_digest_transparency_basic():
    b = Basic(x=7, y="abc")
    dd = DigestedDataclass(
        cls=Basic,
        fields={"x": digest(7), "y": digest("abc")},
    )
    assert digest(dd) == digest(b)


def test_digest_transparency_init_false():
    obj = WithInitFalse(x=3)
    dd = DigestedDataclass(
        cls=WithInitFalse,
        fields={"x": digest(3), "y": digest(6)},
    )
    assert digest(dd) == digest(obj)


def test_digest_transparency_initvar():
    obj = WithInitVar(x=2, y=5)
    # InitVar 'y' is not in dc_fields; only 'x' and 'z' appear.
    dd = DigestedDataclass(
        cls=WithInitVar,
        fields={"x": digest(2), "z": digest(7)},
    )
    assert digest(dd) == digest(obj)


def test_digest_transparency_mixed_plain_and_digest():
    """Partially-digested fields still produce the correct hash."""
    b = Basic(x=5, y="hi")
    dd = DigestedDataclass(
        cls=Basic,
        fields={"x": 5, "y": digest("hi")},
    )
    assert digest(dd) == digest(b)


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------

def test_save_is_deterministic(ds):
    b = Basic(x=1, y="z")
    assert ds.save(b) == ds.save(b)


def test_save_initvar_is_deterministic(ds):
    obj = WithInitVar(x=10, y=20)
    assert ds.save(obj) == ds.save(obj)


# ---------------------------------------------------------------------------
# Dataclass inside containers
# ---------------------------------------------------------------------------

def test_dataclass_in_list_roundtrip(ds):
    data = [Basic(x=1, y="a"), Basic(x=2, y="b")]
    key = ds.save(data)
    loaded = ds.load(key)
    assert loaded == data
    assert all(type(v) is Basic for v in loaded)


def test_dataclass_in_dict_roundtrip(ds):
    data = {"item": Basic(x=3, y="c"), "count": 42}
    key = ds.save(data)
    loaded = ds.load(key)
    assert loaded == data
    assert type(loaded["item"]) is Basic


def test_dataclass_in_tuple_roundtrip(ds):
    data = (Basic(x=4, y="d"), "extra")
    key = ds.save(data)
    loaded = ds.load(key)
    assert loaded == data
    assert type(loaded[0]) is Basic


# ---------------------------------------------------------------------------
# Deduplication: shared field values
# ---------------------------------------------------------------------------

def test_shared_field_list_deduplicated(ds):
    shared = [1, 2, 3]
    # Different meta so the two Nested instances get distinct keys.
    a = Nested(items=shared, meta={"id": 1})
    b = Nested(items=shared, meta={"id": 2})
    key_a = ds.save(a)
    key_b = ds.save(b)
    assert key_a != key_b
    shared_key = digest(shared)
    hits = ds.count_reuses()
    # The same [1,2,3] list is referenced by both DigestedDataclass wrappers.
    assert hits[shared_key] == 2


def test_two_dataclasses_sharing_field_value(ds):
    shared_list = [10, 20]
    dc1 = Nested(items=shared_list, meta={"x": 1})
    dc2 = Nested(items=shared_list, meta={"x": 2})
    ds.save(dc1)
    ds.save(dc2)
    assert ds.load(digest(dc1)) == dc1
    assert ds.load(digest(dc2)) == dc2


# ---------------------------------------------------------------------------
# count_reuses includes DigestedDataclass back-references
# ---------------------------------------------------------------------------

def test_count_reuses_dataclass_fields_tracked():
    ds = make_ds(remaining_depth=0)
    b = Basic(x=1, y="hello")
    key = ds.save(b)
    x_key = digest(1)
    y_key = digest("hello")
    hits = ds.count_reuses()
    assert hits[x_key] == 1
    assert hits[y_key] == 1
    assert hits[key] == 0


def test_count_reuses_nonnegative_for_dataclass():
    ds = make_ds(remaining_depth=0)
    ds.save(WithInitFalse(x=7))
    hits = ds.count_reuses()
    assert all(v >= 0 for v in hits.values())


# ---------------------------------------------------------------------------
# remaining_depth behaviour
# ---------------------------------------------------------------------------

def test_remaining_depth_high_inlines_scalar_fields():
    """With remaining_depth=10 scalar fields are inlined; stored as plain dataclass."""
    ds = make_ds(remaining_depth=10)
    b = Basic(x=1, y="hi")
    key = ds.save(b)
    raw = ds.storage[key]
    # Scalar fields don't warrant separate storage slots -> stored as plain dataclass.
    assert not isinstance(raw, DigestedDataclass)
    assert ds.load(key) == b


def test_remaining_depth_0_destructures_dataclass():
    ds = make_ds(remaining_depth=0)
    b = Basic(x=1, y="hi")
    key = ds.save(b)
    raw = ds.storage[key]
    assert isinstance(raw, DigestedDataclass)
    assert all(isinstance(v, Digest) for v in raw.fields.values())


def test_remaining_depth_roundtrip_various():
    for depth in range(5):
        ds = make_ds(remaining_depth=depth)
        obj = Nested(items=[1, [2, 3]], meta={"k": "v"})
        key = ds.save(obj)
        assert ds.load(key) == obj


@given(remaining_depth=st.integers(min_value=0, max_value=5))
def test_cross_depth_roundtrip_dataclass(remaining_depth):
    shared = {}
    writer = DestructuringMemory(storage=shared, remaining_depth=remaining_depth)
    reader = DestructuringMemory(storage=shared, remaining_depth=0)
    obj = Basic(x=99, y="cross")
    key = writer.save(obj)
    assert reader.load(key) == obj


# ---------------------------------------------------------------------------
# Hypothesis roundtrips
# ---------------------------------------------------------------------------

@settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(st_dataclasses(st_base_values, frozen=True))
def test_hypothesis_frozen_dataclass_roundtrip(ds, dc):
    key = ds.save(dc)
    assert ds.load(key) == dc
    assert type(ds.load(key)) is type(dc)


@settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(st_dataclasses(st_base_values, frozen=False))
def test_hypothesis_mutable_dataclass_roundtrip(ds, dc):
    key = ds.save(dc)
    assert ds.load(key) == dc
    assert type(ds.load(key)) is type(dc)


@settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(st_nested_values)
def test_hypothesis_nested_values_still_roundtrip(ds, value):
    """Adding dataclass support must not break existing nested-value roundtrips."""
    key = ds.save(value)
    assert ds.load(key) == value


@settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(st_dataclasses(st_base_values, frozen=True))
def test_hypothesis_save_deterministic(ds, dc):
    assert ds.save(dc) == ds.save(dc)


# ---------------------------------------------------------------------------
# Interaction with namedtuples (must remain unaffected)
# ---------------------------------------------------------------------------

Point = namedtuple("Point", ["x", "y"])


def test_namedtuple_still_not_destructured(ds):
    """Namedtuples must not be caught by the dataclass branch."""
    p = Point(1, 2)
    key = ds.save(p)
    raw = ds.storage[key]
    assert not isinstance(raw, DigestedDataclass)
    assert type(raw) is Point


# ---------------------------------------------------------------------------
# Fallback: dataclasses that resist destructuring go through whole
# ---------------------------------------------------------------------------

def test_sunder_fallback_on_type_error():
    """sunder returns (value, inf) when fields() raises TypeError."""
    import types
    import fleche.storage.destructuring as destr_mod
    import dataclasses as dc_mod

    @dataclass
    class SomeClass:
        x: int = 1

    obj = SomeClass()
    original_dc = destr_mod._dataclasses  # save BEFORE any replacement

    mock_dc = types.ModuleType("dataclasses_mock")
    mock_dc.fields = lambda o: (_ for _ in ()).throw(TypeError("cannot introspect"))
    mock_dc.is_dataclass = dc_mod.is_dataclass

    def intern_noop(v):
        return v, 0

    destr_mod._dataclasses = mock_dc
    try:
        result, depth = DigestedDataclass.sunder(intern_noop, obj)
    finally:
        destr_mod._dataclasses = original_dc

    assert depth == float("inf")
    assert result is obj


def test_sunder_fallback_on_attribute_error():
    """sunder returns (value, inf) when a field attribute cannot be read."""
    @dataclass
    class HiddenField:
        x: int = field(default=1)

        def __getattribute__(self, name):
            if name == "x":
                raise AttributeError("hidden")
            return super().__getattribute__(name)

    obj = object.__new__(HiddenField)
    object.__setattr__(obj, "x", 42)

    def intern_noop(v):
        return v, 0

    result, depth = DigestedDataclass.sunder(intern_noop, obj)
    assert depth == float("inf")
    assert result is obj


# ---------------------------------------------------------------------------
# Frozen dataclass: object.__setattr__ bypass works for reconstruction
# ---------------------------------------------------------------------------

def test_frozen_dataclass_mend_uses_object_setattr():
    """Frozen dataclasses can be reconstructed even though __setattr__ raises."""
    ds = make_ds(remaining_depth=0)
    f = Frozen(x=10, y=[1, 2, 3])
    key = ds.save(f)
    loaded = ds.load(key)
    assert loaded.x == 10
    assert loaded.y == [1, 2, 3]
    assert type(loaded) is Frozen


# ---------------------------------------------------------------------------
# Fields with init=False that differ from what __post_init__ would recompute
# ---------------------------------------------------------------------------

def test_init_false_mutated_after_construction(ds):
    """If an init=False field is modified after construction, the saved value is restored."""
    obj = WithInitFalse(x=3)
    obj.y = 999  # mutation: no longer x*2
    key = ds.save(obj)
    loaded = ds.load(key)
    assert loaded.x == 3
    assert loaded.y == 999  # restored, NOT recomputed as 6
