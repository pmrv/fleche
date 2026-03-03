import pytest
from fleche.storage import Memory, PickleFile, BagOfHoldingH5File, AmbiguousDigestError
from fleche.digest import DIGEST_LENGTH


@pytest.fixture(params=["memory", "cloudpickle", "dill", "h5"])
def storage(request, tmp_path):
    if request.param == "memory":
        return Memory(storage={})
    elif request.param == "cloudpickle":
        return PickleFile.with_cloudpickle(root=tmp_path)
    elif request.param == "dill":
        return PickleFile.with_dill(root=tmp_path)
    elif request.param == "h5":
        return BagOfHoldingH5File(root=tmp_path)


def test_short_digest_expansion(storage):
    # Create two unique values
    v1 = "value1"
    v2 = "value2"

    k1 = storage.save(v1)
    k2 = storage.save(v2)

    assert len(k1) == DIGEST_LENGTH
    assert len(k2) == DIGEST_LENGTH

    # Test expansion of unique prefix
    for i in range(4, DIGEST_LENGTH):
        prefix = k1[:i]
        if not k2.startswith(prefix):
            assert storage.expand(prefix) == k1
            assert storage.load(prefix) == v1
            break
    else:
        pytest.fail("Could not find a unique prefix for k1")


def test_ambiguous_digest(storage):
    k1 = "a" * 64
    k2 = "a" * 10 + "b" + "a" * 53

    storage.save("val1", k1)
    storage.save("val2", k2)

    # Prefix "aaaa" should be ambiguous
    with pytest.raises(AmbiguousDigestError) as excinfo:
        storage.expand("aaaa")
    assert "need at least 11 characters" in str(excinfo.value)

    with pytest.raises(AmbiguousDigestError):
        storage.load("aaaa")


def test_too_short_digest(storage):
    k1 = storage.save("value1")

    # Prefix "abc" is only 3 chars, should raise KeyError
    with pytest.raises(KeyError):
        storage.expand(k1[:3])

    with pytest.raises(KeyError):
        storage.load(k1[:3])


def test_missing_digest(storage):
    storage.save("value1")

    # Prefix that doesn't exist
    with pytest.raises(KeyError):
        storage.expand("ffff")


def test_full_digest_still_works(storage):
    v1 = "value1"
    k1 = storage.save(v1)

    assert storage.load(k1) == v1
    assert storage.expand(k1) == k1
