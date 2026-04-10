import pytest
from fleche.storage import AmbiguousDigestError
from fleche.digest import DIGEST_LENGTH


def test_short_digest_expansion(value_storage):
    # Create two unique values
    v1 = "value1"
    v2 = "value2"

    k1 = value_storage.save(v1)
    k2 = value_storage.save(v2)

    assert len(k1) == DIGEST_LENGTH
    assert len(k2) == DIGEST_LENGTH

    # Test expansion of unique prefix
    for i in range(4, DIGEST_LENGTH):
        prefix = k1[:i]
        if not k2.startswith(prefix):
            assert value_storage.expand(prefix) == k1
            assert value_storage.load(prefix) == v1
            break
    else:
        pytest.fail("Could not find a unique prefix for k1")


def test_ambiguous_digest(value_storage):
    k1 = "a" * 64
    k2 = "a" * 10 + "b" + "a" * 53

    value_storage.save("val1", k1)
    value_storage.save("val2", k2)

    # Prefix "aaaa" should be ambiguous
    with pytest.raises(AmbiguousDigestError) as excinfo:
        value_storage.expand("aaaa")
    assert "need at least 11 characters" in str(excinfo.value)

    with pytest.raises(AmbiguousDigestError):
        value_storage.load("aaaa")


def test_too_short_digest(value_storage):
    k1 = value_storage.save("value1")

    # Prefix "abc" is only 3 chars, should raise KeyError
    with pytest.raises(KeyError):
        value_storage.expand(k1[:3])

    with pytest.raises(KeyError):
        value_storage.load(k1[:3])


def test_missing_digest(value_storage):
    value_storage.save("value1")

    # Prefix that doesn't exist
    with pytest.raises(KeyError):
        value_storage.expand("ffff")


def test_full_digest_still_works(value_storage):
    v1 = "value1"
    k1 = value_storage.save(v1)

    assert value_storage.load(k1) == v1
    assert value_storage.expand(k1) == k1
