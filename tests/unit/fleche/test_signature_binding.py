import pytest

from fleche import fleche


def test_digest_raises_for_missing_required_argument():
    # Binding should validate required parameters even when only computing a digest
    @fleche
    def f(a, b):
        return a + b

    with pytest.raises(TypeError):
        # Missing required 'b'
        f.fleche.digest(1)

    with pytest.raises(TypeError):
        # Missing required 'a'
        f.fleche.digest(b=2)


def test_digest_raises_for_multiple_values_for_argument():
    @fleche
    def f(a):
        return a

    # Providing both positional and keyword for the same param should raise during binding
    with pytest.raises(TypeError):
        f.fleche.digest(1, a=1)


def test_call_succeeds_with_defaults():
    # Default values are applied during binding (no error raised)
    @fleche
    def f(a, b=10):
        return a + b

    # Should not raise
    _ = f.fleche.call(1)


def test_digest_positional_and_keyword_equivalence():
    @fleche
    def f(a, b):
        return a + b

    # Same logical call expressed differently should map to the same digest
    k_pos = f.fleche.digest(1, 2)
    k_kw = f.fleche.digest(a=1, b=2)
    assert k_pos == k_kw


def test_digest_applies_defaults_in_binding():
    @fleche
    def f(a, b=10):
        return a + b

    # Defaulted arguments should be applied so these produce identical digests
    k_defaulted = f.fleche.digest(1)
    k_explicit = f.fleche.digest(1, b=10)
    assert k_defaulted == k_explicit


def test_ignore_argument_applies_after_binding():
    # When ignoring an argument by name, it should be ignored regardless of how it was provided
    @fleche(ignore=("a",))
    def f(a, b):
        return a + b

    # Since 'a' is ignored, changing it should not change the digest, even if provided positionally
    k1 = f.fleche.digest(1, b=2)
    k2 = f.fleche.digest(2, b=2)
    assert k1 == k2
