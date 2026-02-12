from dataclasses import dataclass
from unittest.mock import Mock

import pytest

from fleche import fleche, cache
from fleche.digest import Digest
from fleche.cache import Cache
from fleche.storage import Memory

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
    c = Cache(Memory({}), Memory({}))
    with cache(c):
        obj = DigestibleClass(10)
        # First call, should be a miss
        assert obj.method(5) == 15
        assert obj.mock.call_count == 1

        # Second call, same instance, same args, should be a hit
        assert obj.method(5) == 15
        assert obj.mock.call_count == 1

def test_method_on_different_instances_same_digest():
    c = Cache(Memory({}), Memory({}))
    with cache(c):
        obj1 = DigestibleClass(10)
        assert obj1.method(5) == 15
        assert obj1.mock.call_count == 1

        obj2 = DigestibleClass(10)
        # Same digest as obj1, should hit the cache even if different instance
        assert obj2.method(5) == 15
        assert obj2.mock.call_count == 0

def test_method_on_mutated_instance():
    c = Cache(Memory({}), Memory({}))
    with cache(c):
        obj = DigestibleClass(10)
        assert obj.method(5) == 15
        assert obj.mock.call_count == 1

        # Mutate the instance - changing self.val changes its digest
        obj.val = 20
        # Should be a miss because the 'self' argument has a different digest
        assert obj.method(5) == 25
        assert obj.mock.call_count == 2

def test_method_on_dataclass():
    digestible_dataclass_mock.reset_mock()
    digestible_dataclass_mock.side_effect = lambda val, x: val + x

    c = Cache(Memory({}), Memory({}))
    with cache(c):
        obj = DigestibleDataclass(10)
        assert obj.method(5) == 15
        assert digestible_dataclass_mock.call_count == 1

        # Same instance, same args
        assert obj.method(5) == 15
        assert digestible_dataclass_mock.call_count == 1

        # Mutation of dataclass
        obj.val = 20
        assert obj.method(5) == 25
        assert digestible_dataclass_mock.call_count == 2
