from dataclasses import dataclass
from unittest.mock import Mock

import pytest

from fleche import fleche
from fleche.caches import Cache
from fleche.digest import Digest
from fleche.state import cache
from fleche.storage import ValueMemory, CallMemory


class DigestibleClass:
    def __init__(self, val):
        self.val = val
        self.mock = Mock()
        self.mock.side_effect = lambda x: self.val + x

    def __digest__(self):
        return Digest(str(self.val))

    @fleche
    def method(self, x):
        return self.mock(x)


@dataclass
class DigestibleDataclass:
    val: int

    @fleche
    def method(self, x):
        return digestible_dataclass_mock(self.val, x)


digestible_dataclass_mock = Mock()


def test_method_on_same_instance():
    # Use a unique value to avoid interference with other tests using the default cache
    obj = DigestibleClass(100)
    # First call, should be a miss
    assert obj.method(5) == 105
    assert obj.mock.call_count == 1

    # Second call, same instance, same args, should be a hit
    assert obj.method(5) == 105
    assert obj.mock.call_count == 1


def test_method_on_different_instances_same_digest():
    obj1 = DigestibleClass(101)
    assert obj1.method(5) == 106
    assert obj1.mock.call_count == 1

    obj2 = DigestibleClass(101)
    # Same digest as obj1, should hit the cache even if different instance
    assert obj2.method(5) == 106
    assert obj2.mock.call_count == 0


def test_method_on_mutated_instance():
    obj = DigestibleClass(102)
    assert obj.method(5) == 107
    assert obj.mock.call_count == 1

    # Mutate the instance - changing self.val changes its digest
    obj.val = 202
    # Should be a miss because the 'self' argument has a different digest
    assert obj.method(5) == 207
    assert obj.mock.call_count == 2


def test_method_on_dataclass():
    digestible_dataclass_mock.reset_mock()
    digestible_dataclass_mock.side_effect = lambda val, x: val + x

    obj = DigestibleDataclass(300)
    assert obj.method(5) == 305
    assert digestible_dataclass_mock.call_count == 1

    # Same instance, same args
    assert obj.method(5) == 305
    assert digestible_dataclass_mock.call_count == 1

    # Mutation of dataclass
    obj.val = 400
    assert obj.method(5) == 405
    assert digestible_dataclass_mock.call_count == 2


# ---------------------------------------------------------------------------
# Helper auto-binding: obj.method.helper() without explicit self=obj
# ---------------------------------------------------------------------------


class _HelperBindClass:
    def __init__(self, val):
        self.val = val

    def __digest__(self):
        return Digest(str(self.val))

    @fleche
    def compute(self, x):
        return self.val + x


def test_method_helpers_auto_bind_self_contains():
    """obj.method.contains(x) should not require self=obj."""
    c = Cache(ValueMemory({}), CallMemory({}))
    obj = _HelperBindClass(42)
    with cache(c):
        obj.compute(5)
        assert obj.compute.contains(5)


def test_method_fleche_namespace_auto_binds():
    """obj.method.fleche.contains(x) should not require self=obj."""
    c = Cache(ValueMemory({}), CallMemory({}))
    obj = _HelperBindClass(42)
    with cache(c):
        obj.compute(5)
        assert obj.compute.fleche.contains(5)


def test_method_helpers_digest_auto_bind_self():
    """obj.method.digest(x) produces the same key as Klass.method.digest(obj, x)."""
    obj = _HelperBindClass(42)
    assert obj.compute.digest(5) == _HelperBindClass.compute.digest(obj, 5)


def test_method_helpers_load_auto_bind_self():
    """obj.method.load(x) retrieves the cached result without explicit self."""
    c = Cache(ValueMemory({}), CallMemory({}))
    obj = _HelperBindClass(42)
    with cache(c):
        obj.compute(5)
        assert obj.compute.load(5) == 47


def test_method_helpers_query_auto_bind_self():
    """obj.method.query(x) returns matching calls without explicit self."""
    c = Cache(ValueMemory({}), CallMemory({}))
    obj = _HelperBindClass(42)
    with cache(c):
        obj.compute(5)
        results = list(obj.compute.query(5))
    assert len(results) == 1
    assert results[0].result == 47


def test_class_access_returns_fleche_wrapper():
    """Accessing @fleche method on the class (not instance) returns FlecheWrapper itself."""
    from fleche.wrapper import FlecheWrapper
    assert isinstance(_HelperBindClass.compute, FlecheWrapper)


def test_instance_access_returns_bound_method():
    """Accessing @fleche method on an instance returns a bound view, not FlecheWrapper."""
    from fleche.wrapper import FlecheWrapper
    obj = _HelperBindClass(42)
    assert not isinstance(obj.compute, FlecheWrapper)
    assert obj.compute is not _HelperBindClass.compute


def test_different_instances_get_independent_bound_methods():
    """Each instance gets its own bound method view (helpers pre-apply the correct obj)."""
    c = Cache(ValueMemory({}), CallMemory({}))
    obj_a = _HelperBindClass(10)
    obj_b = _HelperBindClass(20)
    with cache(c):
        obj_a.compute(5)
        assert obj_a.compute.contains(5)
        assert not obj_b.compute.contains(5)
