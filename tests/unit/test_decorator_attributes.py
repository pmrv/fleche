
from fleche import fleche, Cache, cache
from fleche.storage import Memory
from fleche.call import Call
import pytest

def test_fleche_extra_attributes():
    c = Cache(Memory({}), Memory({}))
    with cache(c):
        @fleche(version=1)
        def add(a, b=1):
            return a + b

        # Test call
        call = add.call(1, b=2)
        assert call.name == "add"
        assert call.args == (1,)
        assert call.kwargs == {"b": 2}
        assert call.version == 1

        # Test digest
        key = add.digest(1, b=2)
        assert isinstance(key, str)

        # Test contains
        assert not add.contains(1, b=2)

        # Run and cache
        assert add(1, b=2) == 3

        # Test contains again
        assert add.contains(1, b=2)

        # Test load
        assert add.load(1, b=2) == 3

def test_hash_settings():
    c = Cache(Memory({}), Memory({}))
    with cache(c):
        @fleche(version=1, hash_version=False)
        def func_no_version(x):
            return x

        call = func_no_version.call(1)
        assert call.version is None

        @fleche(hash_module=False)
        def func_no_module(x):
            return x

        call = func_no_module.call(1)
        assert call.module is None
