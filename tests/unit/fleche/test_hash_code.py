from fleche import fleche, cache
from fleche.caches import Cache
from fleche.storage import Memory


def test_hash_code_invalidates_on_change():
    def func_v1(x):
        return x + 1

    def func_v2(x):
        return x + 2

    # We want to simulate the SAME function (same name, same module) but different code.
    func_v1.__name__ = "my_func"
    func_v2.__name__ = "my_func"
    func_v1.__module__ = "my_module"
    func_v2.__module__ = "my_module"

    wrapped_v1 = fleche(hash_code=True)(func_v1)
    wrapped_v2 = fleche(hash_code=True)(func_v2)

    assert wrapped_v1.digest(10) != wrapped_v2.digest(10)


def test_hash_code_default_ignores_change():
    def func_v1(x):
        return x + 1

    def func_v2(x):
        return x + 2

    func_v1.__name__ = "my_func"
    func_v2.__name__ = "my_func"
    func_v1.__module__ = "my_module"
    func_v2.__module__ = "my_module"

    wrapped_v1 = fleche(hash_code=False)(func_v1)
    wrapped_v2 = fleche(hash_code=False)(func_v2)

    assert wrapped_v1.digest(10) == wrapped_v2.digest(10)
