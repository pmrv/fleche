from dataclasses import dataclass
from unittest.mock import Mock

import pytest

from fleche import fleche
from fleche.digest import Digest


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
