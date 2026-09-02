"""``FunctionProfile.code_digest`` and its participation in the lookup key.

Layer note: this file owns the *call* end — how ``code_digest`` is derived
from a callable and what it does to the key.  What a function digest is made
of belongs in ``tests/unit/digest/test_digest.py``; this file covers only
what ``call.py`` adds on top: the warn-and-fall-back on an indigestible
capture, and the bound-method reduction.
"""

import logging

from fleche.call import Call
from fleche.digest import digest


def test_code_digest_is_hashed_in_lookup_key():
    """
    Verify that two Call objects which differ ONLY by their code_digest
    produce different lookup keys.
    """
    call_a = Call(name="foo", arguments={"x": 1}, code_digest="abc")
    call_b = Call(name="foo", arguments={"x": 1}, code_digest="xyz")

    assert call_a.to_lookup_key() != call_b.to_lookup_key()


def test_code_digest_none_vs_string():
    """
    Verify that a Call with no code_digest differs from one with a code_digest.
    """
    call_none = Call(name="foo", arguments={"x": 1}, code_digest=None)
    call_str = Call(name="foo", arguments={"x": 1}, code_digest="abc")

    assert call_none.to_lookup_key() != call_str.to_lookup_key()


def test_from_call_populates_code_digest():
    """
    Verify that Call.from_call correctly populates the code_digest field
    from the function's __code__ object.
    """

    def my_func(x):
        return x + 1

    call = Call.from_call(my_func, 10)

    assert call.code_digest is not None
    assert isinstance(call.code_digest, str)
    # Basic sanity check that it looks like a hex digest
    assert len(call.code_digest) > 0


def test_different_function_implementations_have_different_digests():
    """
    Verify that two functions with the same name but different bytecode
    result in Call objects with different code_digests and lookup keys.
    """

    def func_v1(x):
        return x + 1

    def func_v2(x):
        return x + 2

    # Ensure metadata matches so only code differs
    func_v1.__name__ = "my_func"
    func_v2.__name__ = "my_func"
    func_v1.__qualname__ = "my_func"
    func_v2.__qualname__ = "my_func"
    func_v1.__module__ = __name__
    func_v2.__module__ = __name__

    call_v1 = Call.from_call(func_v1, 5)
    call_v2 = Call.from_call(func_v2, 5)

    assert call_v1.name == call_v2.name
    assert call_v1.module == call_v2.module
    assert call_v1.arguments == call_v2.arguments

    # The crucial check: code_digest must differ
    assert call_v1.code_digest != call_v2.code_digest
    assert call_v1.to_lookup_key() != call_v2.to_lookup_key()


def test_same_function_implementation_has_same_digest():
    """
    Verify that two functions with identical implementation (and metadata)
    result in the same code_digest.
    """

    # Define two identical functions in different scopes/names to start
    def func_a(x):
        return x * x

    def func_b(x):
        return x * x

    func_a.__name__ = "func"
    func_b.__name__ = "func"
    func_a.__qualname__ = "func"
    func_b.__qualname__ = "func"
    func_a.__module__ = __name__
    func_b.__module__ = __name__

    # Note: Python might compile these to identical code objects.
    # We rely on fleche.digest.digest(code_object) stability.

    call_a = Call.from_call(func_a, 2)
    call_b = Call.from_call(func_b, 2)

    assert call_a.code_digest == call_b.code_digest
    assert call_a.to_lookup_key() == call_b.to_lookup_key()


def _multiplier(n):
    """Factory whose products share a code object and differ only in what they capture."""
    def mul(x):
        return x * n
    return mul


def test_closures_from_the_same_factory_have_different_code_digests():
    """A code-only digest cannot tell two closures apart; the captured cells can."""
    call_2 = Call.from_call(_multiplier(2), 5)
    call_3 = Call.from_call(_multiplier(3), 5)

    assert call_2.code_digest != call_3.code_digest
    assert call_2.to_lookup_key() != call_3.to_lookup_key()


def test_closures_capturing_equal_values_share_a_code_digest():
    """Same code, same captures — same key, so the cache still hits."""
    assert Call.from_call(_multiplier(2), 5).code_digest == Call.from_call(_multiplier(2), 5).code_digest


def test_indigestible_capture_falls_back_to_the_code_digest_with_a_warning(caplog):
    """A closure over something unhashable stays decoratable, loudly.

    Falling back re-opens the collision the captured cells would have closed, so
    it has to be visible rather than silent.
    """
    class Opaque:
        pass

    def make(o):
        def f(x):
            return x, o
        return f

    opaque = make(Opaque())
    with caplog.at_level(logging.WARNING, logger="fleche.call"):
        call = Call.from_call(opaque, 1)

    assert "captured" in caplog.text
    # the fallback is exactly the old behaviour: code only, captures ignored
    assert call.code_digest == digest(opaque.__code__)
    assert call.code_digest == Call.from_call(make(Opaque()), 1).code_digest


def test_bound_method_code_digest_ignores_the_receiver():
    """A bound method's ``code_digest`` comes from the underlying function.

    ``digest(obj.method)`` folds the receiver in, but the receiver also arrives
    as an ordinary argument of the call, so folding it into ``code_digest`` too
    would record it twice — and would refuse every receiver ``fleche`` cannot
    hash.  ``_code_digest`` reduces to ``__func__`` for that reason.
    """

    class Counter:
        def __init__(self, start):
            self.start = start

        def advance(self, by):
            return self.start + by

    one, two = Counter(1), Counter(2)

    # the receiver is opaque to fleche, so a receiver-sensitive code_digest
    # would have to fall back; instead it is simply not part of it
    assert Call.from_call(one.advance, 1).code_digest == Call.from_call(two.advance, 1).code_digest
    assert Call.from_call(one.advance, 1).code_digest == Call.from_call(Counter.advance, one, 1).code_digest
