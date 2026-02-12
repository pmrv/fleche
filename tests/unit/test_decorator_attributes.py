
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
        inv = add.call(1, b=2)
        assert inv.name == "add"
        assert inv.args == (1,)
        assert inv.kwargs == {"b": 2}
        assert inv.version == 1

        # Test key
        key = add.key(1, b=2)
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

        inv = func_no_version.call(1)
        assert inv.version is None

        @fleche(hash_module=False)
        def func_no_module(x):
            return x

        inv = func_no_module.call(1)
        assert inv.module is None
