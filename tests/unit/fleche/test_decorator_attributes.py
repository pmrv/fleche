import inspect
from typing import Iterable


from fleche import fleche, cache
from fleche.call import Call
from fleche.caches import Cache
from fleche.digest import Digest
from fleche.storage import ValueMemory, CallMemory


def test_fleche_extra_attributes():
    c = Cache(ValueMemory({}), CallMemory({}))
    with cache(c):

        call_count = 0

        @fleche(version=1)
        def add(a, b=1):
            nonlocal call_count
            call_count += 1
            return a + b

        # Test call
        call = add.call(1, b=2)
        assert call.name == "add"
        assert list(call.arguments.items()) == [("a", 1), ("b", 2)]
        assert call.version == 1

        # Test digest
        key = add.digest(1, b=2)
        assert isinstance(key, str)

        # Test contains
        assert not add.contains(1, b=2)

        # Run and cache
        assert add(1, b=2) == 3
        assert call_count == 1

        # Test contains again
        assert add.contains(1, b=2)

        # Test load
        assert add.load(1, b=2) == 3

        assert add.rerun(1, b=2) == 3
        assert call_count == 2


def test_hash_settings():
    c = Cache(ValueMemory({}), CallMemory({}))
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


def test_wrapper_helper_metadata():
    @fleche
    def my_func(a: int, b: str = "default") -> float:
        """My original docstring."""
        return 1.0

    # Test .call
    assert my_func.call.__name__ == "call"
    assert "Get the Call object for my_func" in my_func.call.__doc__
    assert "My original docstring." in my_func.call.__doc__
    sig = inspect.signature(my_func.call)
    # Since we no longer use __signature__, inspect.signature follows __wrapped__ to my_func
    assert str(sig) == "(a: int, b: str = 'default') -> float"
    # But __annotations__ on the helper itself should be correct
    assert my_func.call.__annotations__["return"] == Call

    # Test .digest
    assert my_func.digest.__name__ == "digest"
    assert "Get the cache key for my_func" in my_func.digest.__doc__
    assert "My original docstring." in my_func.digest.__doc__
    sig = inspect.signature(my_func.digest)
    assert str(sig) == "(a: int, b: str = 'default') -> float"
    assert my_func.digest.__annotations__["return"] == Digest

    # Test .load
    assert my_func.load.__name__ == "load"
    assert "Load result from cache for my_func" in my_func.load.__doc__
    assert "My original docstring." in my_func.load.__doc__
    sig = inspect.signature(my_func.load)
    assert str(sig) == "(a: int, b: str = 'default') -> float"
    # load returns original return type, which it inherits from wraps(func)

    # Test .contains
    assert my_func.contains.__name__ == "contains"
    assert "Check if result is in cache for my_func" in my_func.contains.__doc__
    assert "My original docstring." in my_func.contains.__doc__
    sig = inspect.signature(my_func.contains)
    assert str(sig) == "(a: int, b: str = 'default') -> float"
    assert my_func.contains.__annotations__["return"] is bool

    # Test .query
    assert my_func.query.__name__ == "query"
    assert (
        "Return matching results from current cache for my_func"
        in my_func.query.__doc__
    )
    assert "Return matching results from current cache." in my_func.query.__doc__
    sig = inspect.signature(my_func.query)
    # Sig is from my_func due to @wraps(func)
    assert str(sig) == "(a: int, b: str = 'default') -> float"
    assert my_func.query.__annotations__["return"] == Iterable[Call]
