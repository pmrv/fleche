import pytest

from fleche import fleche
from fleche.digest import Unhashable


class UnhashableThing:
    pass


def test_call_drops_ignored_arguments():
    @fleche(ignore=("a",))
    def f(a, b):
        return a + b

    c = f.call(1, b=2)
    assert "a" not in c.arguments
    assert set(c.arguments.keys()) == {"b"}


def test_digest_ignores_ignored_argument_all_supported_binding_forms():
    # a can be provided positionally or by keyword; b can be positional or keyword
    @fleche(ignore=("a",))
    def f(a, b):
        return a + b

    # keep b the same; vary a and how it’s provided
    k_pos_pos_1 = f.digest(1, 2)
    k_pos_pos_2 = f.digest(999, 2)

    k_pos_kw_1 = f.digest(1, b=2)
    k_pos_kw_2 = f.digest(999, b=2)

    k_kw_kw_1 = f.digest(a=1, b=2)
    k_kw_kw_2 = f.digest(a=999, b=2)

    # All should be equal because 'a' is ignored
    assert k_pos_pos_1 == k_pos_pos_2 == k_pos_kw_1 == k_pos_kw_2 == k_kw_kw_1 == k_kw_kw_2


def test_non_ignored_argument_changes_digest():
    @fleche(ignore=("a",))
    def f(a, b):
        return a + b

    k1 = f.digest(1, b=2)
    k2 = f.digest(1, b=3)
    assert k1 != k2


def test_multiple_ignored_arguments():
    @fleche(ignore=("a", "c"))
    def f(a, b, c):
        return a + b + c

    # Vary ignored a and c: digest unchanged
    k1 = f.digest(1, 2, 3)
    k2 = f.digest(10, 2, 30)
    assert k1 == k2

    # Change non-ignored b: digest changes
    k3 = f.digest(1, 99, 3)
    assert k1 != k3


def test_ignore_string_list_tuple_equivalent():
    @fleche(ignore="a")
    def f_str(a, b):
        return a + b

    @fleche(ignore=["a"])  # list form
    def f_list(a, b):
        return a + b

    @fleche(ignore=("a",))  # tuple form
    def f_tuple(a, b):
        return a + b

    # Each form should ignore 'a' consistently within the same function
    k1a = f_str.digest(1, b=2)
    k1b = f_str.digest(999, b=2)
    assert k1a == k1b

    k2a = f_list.digest(1, b=2)
    k2b = f_list.digest(999, b=2)
    assert k2a == k2b

    k3a = f_tuple.digest(1, b=2)
    k3b = f_tuple.digest(999, b=2)
    assert k3a == k3b


def test_unignored_unhashable_raises_but_ignored_is_ok():
    # Without ignore, an unhashable argument should cause digest to raise
    @fleche
    def g(x):
        return 1

    with pytest.raises(Unhashable):
        _ = g.digest(UnhashableThing())

    # With ignore, the same unhashable value should be fine and not affect digest
    @fleche(ignore=("x",))
    def h(x, y):
        return y

    try:
        h.digest(UnhashableThing(), y=2)
    except Unhashable:
        assert False


def test_keyword_only_and_positional_only_params_with_ignore():
    # Positional-only 'a'
    @fleche(ignore=("a",))
    def f(a, /, b):
        return a + b

    k1 = f.digest(1, 2)
    k2 = f.digest(999, 2)
    assert k1 == k2  # varying ignored positional-only 'a' has no effect

    k3 = f.digest(1, 3)
    assert k1 != k3  # changing non-ignored 'b' affects digest

    # Keyword-only 'b'
    @fleche(ignore=("b",))
    def g(a, *, b):
        return a + b

    k4 = g.digest(1, b=2)
    k5 = g.digest(1, b=999)
    assert k4 == k5  # varying ignored keyword-only 'b' has no effect


def test_defaults_with_ignored_argument():
    @fleche(ignore=("a",))
    def f(a=1, b=2):
        return a + b

    # Even though 'a' has a default (and is present in bound args), ignoring it should make these equal
    k_default = f.digest()
    k_override_ignored = f.digest(a=999)
    assert k_default == k_override_ignored
