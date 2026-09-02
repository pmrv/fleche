"""The ``hash_code=`` decorator kwarg: whether ``code_digest`` reaches the key.

Layer note: this file owns the *decorator* end — that the flag plumbs
``code_digest`` into the lookup key at all.  What that digest is made of is
``tests/unit/digest/test_digest.py``; a real cache round-trip is
``tests/integration/test_hash_code_integration.py``.
"""

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
    """``hash_code=True`` carries captured variables into the key.

    Closures out of one factory agree on qualname, module *and* code object, so
    the captured values are the only thing that can separate their keys.  That
    they then miss each other's cache entries is
    ``tests/integration/test_hash_code_integration.py``.
    """
    def make(n):
        def scale(x):
            return x * n
        return scale

    double = fleche(hash_code=True)(make(2))
    triple = fleche(hash_code=True)(make(3))

    assert double.fleche.digest(5) != triple.fleche.digest(5)


def test_hash_code_false_ignores_captured_values():
    """Without the flag nothing separates two closures out of one factory.

    Documented in ``USAGE.md`` and ``digests/digest_equivalence.rst`` rather than
    changed: flipping the default would invalidate every existing cache.
    """
    def make(n):
        def scale(x):
            return x * n
        return scale

    assert fleche()(make(2)).fleche.digest(5) == fleche()(make(3)).fleche.digest(5)
