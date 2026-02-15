import pytest
from fleche.storage import Memory, AmbiguousDigestError
from fleche.digest import DIGEST_LENGTH

def test_short_digest_expansion_memory():
    storage = Memory(storage={})

    # Create two unique values
    v1 = "value1"
    v2 = "value2"

    k1 = storage.save(v1)
    k2 = storage.save(v2)

    assert len(k1) == DIGEST_LENGTH
    assert len(k2) == DIGEST_LENGTH

    # Test expansion of unique prefix
    # Find a prefix of k1 that is not a prefix of k2
    for i in range(4, DIGEST_LENGTH):
        prefix = k1[:i]
        if not k2.startswith(prefix):
            assert storage.expand(prefix) == k1
            assert storage.load(prefix) == v1
            break
    else:
        pytest.fail("Could not find a unique prefix for k1")

def test_ambiguous_digest_memory():
    storage = Memory(storage={})

    # We need two keys with same prefix.
    # Since we use sha256, it's hard to find collisions.
    # But we can manually inject them into the storage dictionary for testing expand().

    k1 = "a" * 64
    k2 = "a" * 10 + "b" + "a" * 53

    storage.storage[k1] = "val1"
    storage.storage[k2] = "val2"

    # Prefix "aaaa" should be ambiguous
    with pytest.raises(AmbiguousDigestError):
        storage.expand("aaaa")

    with pytest.raises(AmbiguousDigestError):
        storage.load("aaaa")

def test_too_short_digest():
    storage = Memory(storage={})
    k1 = storage.save("value1")

    # Prefix "abc" is only 3 chars, should raise KeyError
    with pytest.raises(KeyError):
        storage.expand(k1[:3])

    with pytest.raises(KeyError):
        storage.load(k1[:3])

def test_missing_digest():
    storage = Memory(storage={})
    storage.save("value1")

    # Prefix that doesn't exist
    with pytest.raises(KeyError):
        storage.expand("ffff")

def test_full_digest_still_works():
    storage = Memory(storage={})
    v1 = "value1"
    k1 = storage.save(v1)

    assert storage.load(k1) == v1
    assert storage.expand(k1) == k1

def test_cloudpickle_file_storage_short_digest(tmp_path):
    from fleche.storage import CloudpickleFile
    storage = CloudpickleFile(root=tmp_path)

    v1 = {"a": 1, "b": 2}
    k1 = storage.save(v1)

    # Test expansion
    prefix = k1[:10]
    assert storage.expand(prefix) == k1
    assert storage.load(prefix) == v1
