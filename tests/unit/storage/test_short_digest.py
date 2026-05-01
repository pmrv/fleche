import pytest
from fleche.storage import AmbiguousDigestError, ValueMemory
from fleche.storage.base import _longest_common_prefix_length
from fleche.digest import DIGEST_LENGTH


def test_short_digest_expansion():
    store = ValueMemory({})
    v1 = "value1"
    v2 = "value2"

    k1 = store.save(v1)
    k2 = store.save(v2)

    assert len(k1) == DIGEST_LENGTH
    assert len(k2) == DIGEST_LENGTH

    for i in range(4, DIGEST_LENGTH):
        prefix = k1[:i]
        if not k2.startswith(prefix):
            assert store.expand(prefix) == k1
            assert store.load(prefix) == v1
            break
    else:
        pytest.fail("Could not find a unique prefix for k1")


def test_ambiguous_digest():
    store = ValueMemory({})
    k1 = "a" * 64
    k2 = "a" * 10 + "b" + "a" * 53

    store.save("val1", k1)
    store.save("val2", k2)

    with pytest.raises(AmbiguousDigestError) as excinfo:
        store.expand("aaaa")
    assert "need at least 11 characters" in str(excinfo.value)

    with pytest.raises(AmbiguousDigestError):
        store.load("aaaa")


def test_too_short_digest():
    store = ValueMemory({})
    k1 = store.save("value1")

    with pytest.raises(KeyError):
        store.expand(k1[:3])

    with pytest.raises(KeyError):
        store.load(k1[:3])


def test_missing_digest():
    store = ValueMemory({})
    store.save("value1")

    with pytest.raises(KeyError):
        store.expand("ffff")


class TestLongestCommonPrefixLength:
    def test_identical_strings(self):
        assert _longest_common_prefix_length("abcd", "abcd") == 4

    def test_no_common_prefix(self):
        assert _longest_common_prefix_length("abc", "xyz") == 0

    def test_partial_common_prefix(self):
        assert _longest_common_prefix_length("abcX", "abcY") == 3

    def test_one_is_prefix_of_other(self):
        assert _longest_common_prefix_length("abc", "abcdef") == 3

    def test_empty_strings(self):
        assert _longest_common_prefix_length("", "") == 0

    def test_one_empty(self):
        assert _longest_common_prefix_length("", "abc") == 0
