import inspect
from typing import Iterable
from fleche import fleche
from fleche.call import Call
from fleche.digest import Digest


def test_wrapper_metadata():
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
    assert my_func.contains.__annotations__["return"] == bool

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
