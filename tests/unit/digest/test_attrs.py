"""Tests verifying that attrs-based classes can be hashed and interoperate with fleche.

Covers digest support for both new-style (``@attrs.define``) and old-style
(``@attr.s``) attrs classes, parity with dataclasses where it makes sense, and
integration with the @fleche decorator and destructuring storage.
"""

from dataclasses import dataclass, make_dataclass

import attr
import attrs
import pytest

from fleche import fleche, cache
from fleche.caches import Cache
from fleche.digest import digest, Digest
from fleche.storage import CallMemory, ValueMemory, ValueMixin, DestructuringMixin
from fleche.storage.destructuring import DigestedAttrs, DigestedDataclass
from fleche.storage.memory import MemoryBackend


# ---------------------------------------------------------------------------
# attrs class shapes
# ---------------------------------------------------------------------------


@attrs.define
class AttrsBasic:
    x: int
    y: str


@attrs.define(frozen=True)
class AttrsFrozen:
    x: int
    y: str


@attr.s
class AttrSBasic:
    x = attr.ib(type=int)
    y = attr.ib(type=str)


@attrs.define
class AttrsNested:
    inner: AttrsBasic
    tag: str


@attrs.define
class AttrsWithCollections:
    items: list
    meta: dict


@attrs.define
class AttrsEmpty:
    pass


# ---------------------------------------------------------------------------
# Basic digest tests
# ---------------------------------------------------------------------------


def test_attrs_define_can_be_digested():
    a = AttrsBasic(x=1, y="hi")
    d = digest(a)
    assert isinstance(d, Digest)
    assert len(d) == 64


def test_attrs_frozen_can_be_digested():
    a = AttrsFrozen(x=1, y="hi")
    d = digest(a)
    assert isinstance(d, Digest)


def test_old_style_attr_s_can_be_digested():
    a = AttrSBasic(x=1, y="hi")
    d = digest(a)
    assert isinstance(d, Digest)


def test_attrs_digest_is_stable():
    assert digest(AttrsBasic(x=1, y="hi")) == digest(AttrsBasic(x=1, y="hi"))


def test_attrs_digest_distinguishes_field_values():
    assert digest(AttrsBasic(x=1, y="hi")) != digest(AttrsBasic(x=2, y="hi"))
    assert digest(AttrsBasic(x=1, y="hi")) != digest(AttrsBasic(x=1, y="bye"))


def test_attrs_digest_distinguishes_classes():
    """Two different attrs classes with identical fields must hash differently."""

    @attrs.define
    class A:
        x: int

    @attrs.define
    class B:
        x: int

    assert digest(A(x=1)) != digest(B(x=1))


def test_attrs_empty_can_be_digested():
    digest(AttrsEmpty())


def test_attrs_nested_can_be_digested():
    a = AttrsNested(inner=AttrsBasic(x=1, y="hi"), tag="t")
    assert isinstance(digest(a), Digest)


def test_attrs_with_collections_can_be_digested():
    a = AttrsWithCollections(items=[1, 2, 3], meta={"k": "v"})
    assert isinstance(digest(a), Digest)


# ---------------------------------------------------------------------------
# Parity with equivalent dataclass: attrs and dataclass with same name and
# field layout should hash the same way (so callers can swap implementations
# without invalidating their cache).
# ---------------------------------------------------------------------------


def test_attrs_matches_equivalent_dataclass_digest():
    """An attrs class and a dataclass with the same name and fields hash identically."""

    @attrs.define
    class Mirror:
        x: int
        y: str

    Dc = make_dataclass("Mirror", [("x", int), ("y", str)])

    assert digest(Mirror(x=1, y="hi")) == digest(Dc(x=1, y="hi"))


# ---------------------------------------------------------------------------
# Merkle-tree property: replacing a sub-value with its digest is invisible.
# ---------------------------------------------------------------------------


def test_attrs_merkle_property_via_nested():
    a = AttrsNested(inner=AttrsBasic(x=1, y="hi"), tag="t")
    a_digested_inner = AttrsNested(inner=digest(AttrsBasic(x=1, y="hi")), tag="t")
    assert digest(a) == digest(a_digested_inner)


# ---------------------------------------------------------------------------
# Integration with @fleche decorator: attrs args are valid cache keys, and
# results that are attrs instances round-trip through the cache.
# ---------------------------------------------------------------------------


def test_fleche_caches_call_with_attrs_argument():
    calls = {"n": 0}

    @fleche
    def f(obj):
        calls["n"] += 1
        return obj.x + len(obj.y)

    with cache(Cache(ValueMemory({}), CallMemory({}))):
        a = AttrsBasic(x=10, y="hi")
        assert f(a) == 12
        assert f(a) == 12  # cache hit, function not re-run
        assert calls["n"] == 1


def test_fleche_caches_attrs_result():
    @fleche
    def make(x, y):
        return AttrsBasic(x=x, y=y)

    with cache(Cache(ValueMemory({}), CallMemory({}))):
        a = make(1, "hi")
        b = make(1, "hi")
        assert a == b
        assert isinstance(b, AttrsBasic)


def test_fleche_distinguishes_different_attrs_arguments():
    @fleche
    def f(obj):
        return obj.x

    with cache(Cache(ValueMemory({}), CallMemory({}))):
        assert f(AttrsBasic(x=1, y="a")) == 1
        assert f(AttrsBasic(x=2, y="a")) == 2


# ---------------------------------------------------------------------------
# Destructuring-storage integration: attrs instances should be destructured
# into a per-field representation just like dataclasses.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DestructuringMemory(DestructuringMixin, ValueMixin, MemoryBackend):
    pass


@pytest.fixture
def ds():
    return DestructuringMemory(storage={})


def test_attrs_destructuring_roundtrip(ds):
    a = AttrsBasic(x=42, y="hello")
    key = ds.save(a)
    loaded = ds.load(key)
    assert loaded == a
    assert type(loaded) is AttrsBasic


def test_attrs_frozen_destructuring_roundtrip(ds):
    a = AttrsFrozen(x=1, y="hi")
    key = ds.save(a)
    loaded = ds.load(key)
    assert loaded == a
    assert type(loaded) is AttrsFrozen


def test_old_style_attr_s_destructuring_roundtrip(ds):
    a = AttrSBasic(x=1, y="hi")
    key = ds.save(a)
    loaded = ds.load(key)
    assert loaded == a
    assert type(loaded) is AttrSBasic


def test_nested_attrs_destructuring_roundtrip(ds):
    outer = AttrsNested(inner=AttrsBasic(x=7, y="z"), tag="t")
    key = ds.save(outer)
    loaded = ds.load(key)
    assert loaded == outer
    assert type(loaded) is AttrsNested
    assert type(loaded.inner) is AttrsBasic


def test_attrs_stored_as_digested_attrs(ds):
    """attrs instances should be destructured into a DigestedAttrs marker.

    Mirrors :class:`DigestedDataclass` for stdlib dataclasses but is a distinct
    subclass so each record kind owns its own field-extraction logic.
    """
    a = AttrsBasic(x=1, y="hello")
    key = ds.save(a)
    raw = ds.storage[key]
    assert isinstance(raw, DigestedAttrs)
    assert not isinstance(raw, DigestedDataclass)
    assert raw.cls is AttrsBasic
