from fleche import fleche

def test_hash_code_invalidates_on_change():
    def func_v1(x):
        return x + 1

    def func_v2(x):
        return x + 2

    # We want to simulate the SAME function (same name, same module) but different code.
    func_v1.__name__ = "my_func"
    func_v2.__name__ = "my_func"
    func_v1.__qualname__ = "my_func"
    func_v2.__qualname__ = "my_func"
    func_v1.__module__ = "my_module"
    func_v2.__module__ = "my_module"

    wrapped_v1 = fleche(hash_code=True)(func_v1)
    wrapped_v2 = fleche(hash_code=True)(func_v2)

    assert wrapped_v1.fleche.digest(10) != wrapped_v2.fleche.digest(10)


def test_hash_code_default_ignores_change():
    def func_v1(x):
        return x + 1

    def func_v2(x):
        return x + 2

    func_v1.__name__ = "my_func"
    func_v2.__name__ = "my_func"
    func_v1.__qualname__ = "my_func"
    func_v2.__qualname__ = "my_func"
    func_v1.__module__ = "my_module"
    func_v2.__module__ = "my_module"

    wrapped_v1 = fleche(hash_code=False)(func_v1)
    wrapped_v2 = fleche(hash_code=False)(func_v2)

    assert wrapped_v1.fleche.digest(10) == wrapped_v2.fleche.digest(10)


def test_hash_code_separates_closures_over_different_values():
    """Two closures out of one factory must not share a cache entry.

    They agree on qualname, module and code object, so before captured variables
    were digested ``make(3)(5)`` returned ``make(2)``'s cached 10.
    """
    def make(n):
        def scale(x):
            return x * n
        return scale

    double = fleche(hash_code=True)(make(2))
    triple = fleche(hash_code=True)(make(3))

    assert double.fleche.digest(5) != triple.fleche.digest(5)
    assert double(5) == 10
    assert triple(5) == 15


def test_hash_code_shares_key_for_closures_over_equal_values():
    """Equal captures still hit the same entry — this is a cache, after all."""
    def make(n):
        def scale(x):
            return x * n
        return scale

    assert fleche(hash_code=True)(make(2)).fleche.digest(5) == fleche(hash_code=True)(make(2)).fleche.digest(5)
