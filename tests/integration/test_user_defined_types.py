from dataclasses import dataclass
from unittest.mock import Mock

import pytest

from fleche import fleche, cache
from fleche.digest import add_hook, Digest
from fleche.cache import Cache
from fleche.storage import Memory

class DigestibleClass:
    def __init__(self, val):
        self.val = val
        self.mock = Mock()
        self.mock.return_value = val

    def __digest__(self):
        return Digest(str(self.val))

    @fleche
    def method(self, x):
        return self.mock(x) + x

@dataclass
class DigestibleDataclass:
    val: int

    @fleche
    def method(self, x):
        # We need a way to track calls.
        # Since we can't easily put a Mock in a dataclass that we want to digest (it might not be digestible),
        # we'll use a global mock for this test.
        return digestible_dataclass_mock(self.val, x)

digestible_dataclass_mock = Mock()

class HookClass:
    def __init__(self, val):
        self.val = val

    @fleche
    def method(self, x):
        return hook_class_mock(self.val, x)

hook_class_mock = Mock()

def hook_class_digest(obj):
    return Digest(f"HookClass:{obj.val}")

add_hook((HookClass, hook_class_digest))

def test_method_with_digest_method():
    c = Cache(Memory({}), Memory({}))
    with cache(c):
        obj = DigestibleClass(10)
        assert obj.method(5) == 15
        assert obj.method(5) == 15
        assert obj.mock.call_count == 1

        obj2 = DigestibleClass(10)
        assert obj2.method(5) == 15
        # obj2 has its own mock, but since the call is cached based on digest,
        # it should NOT call obj2.mock if it hits the cache from obj.
        assert obj2.mock.call_count == 0

        obj3 = DigestibleClass(20)
        assert obj3.method(5) == 25
        assert obj3.mock.call_count == 1

def test_method_on_dataclass():
    digestible_dataclass_mock.reset_mock()
    digestible_dataclass_mock.side_effect = lambda val, x: val + x

    c = Cache(Memory({}), Memory({}))
    with cache(c):
        obj = DigestibleDataclass(10)
        assert obj.method(5) == 15
        assert obj.method(5) == 15
        assert digestible_dataclass_mock.call_count == 1

        obj2 = DigestibleDataclass(10)
        assert obj2.method(5) == 15
        assert digestible_dataclass_mock.call_count == 1

        obj3 = DigestibleDataclass(20)
        assert obj3.method(5) == 25
        assert digestible_dataclass_mock.call_count == 2

def test_method_with_hook():
    hook_class_mock.reset_mock()
    hook_class_mock.side_effect = lambda val, x: val + x

    c = Cache(Memory({}), Memory({}))
    with cache(c):
        obj = HookClass(10)
        assert obj.method(5) == 15
        assert obj.method(5) == 15
        assert hook_class_mock.call_count == 1

        obj2 = HookClass(10)
        assert obj2.method(5) == 15
        assert hook_class_mock.call_count == 1

        obj3 = HookClass(20)
        assert obj3.method(5) == 25
        assert hook_class_mock.call_count == 2
