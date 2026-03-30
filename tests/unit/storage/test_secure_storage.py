import pickle
import pytest
from fleche.storage.pickle_file import PickleFile, _normalize_secret_key


def test_secure_storage_tampering(tmp_path):
    """Test that tampering with the file content raises KeyError."""
    key = b"A" * 32
    storage = PickleFile.with_pickle(root=tmp_path, secret_key=[key])

    value = {"a": 1}
    digest_key = storage.save(value)

    # Tamper with the file
    file_path = tmp_path / digest_key
    content = file_path.read_bytes()

    # Let's prepend garbage to the beginning, which changes the data and should invalidate the signature
    tampered_content = b"garbage" + content
    file_path.write_bytes(tampered_content)

    with pytest.raises(KeyError, match="Value present but failed signature check."):
        storage.load(digest_key)


def test_secure_storage_unsigned_data_fails_when_auth_enabled(tmp_path):
    """Test that unsigned data fails to load when an authenticated storage reads it."""
    # First, write unsigned data (no secret key)
    storage_noauth = PickleFile.with_pickle(root=tmp_path, secret_key=[])
    value = "test"
    digest_key = storage_noauth.save(value)

    # Now try to read it with an authenticated storage
    key = b"B" * 32
    storage_auth = PickleFile.with_pickle(root=tmp_path, secret_key=[key])

    # Should fail to load because security is enabled but no signature exists
    with pytest.raises(KeyError, match="Value present but failed signature check."):
        storage_auth.load(digest_key)


def test_secure_storage_wrong_key(tmp_path):
    """Test that data signed with a different key cannot be loaded."""
    key1 = b"1" * 32
    key2 = b"2" * 32

    storage1 = PickleFile.with_pickle(root=tmp_path, secret_key=[key1])
    storage2 = PickleFile.with_pickle(root=tmp_path, secret_key=[key2])

    value = "secret"
    digest_key = storage1.save(value)

    # Try to load with wrong key
    with pytest.raises(KeyError, match="Value present but failed signature check."):
        storage2.load(digest_key)


def test_secure_storage_roundtrip(tmp_path):
    """Test normal save/load operation."""
    key = b"C" * 32
    storage = PickleFile.with_pickle(root=tmp_path, secret_key=[key])

    value = [1, 2, 3]
    digest_key = storage.save(value)
    loaded = storage.load(digest_key)

    assert loaded == value


def test_storage_noop_no_key(tmp_path):
    """Test that storage works as normal (unsigned) when no key is provided."""
    storage = PickleFile.with_pickle(root=tmp_path, secret_key=[])

    value = "insecure data"
    digest_key = storage.save(value)

    file_path = tmp_path / digest_key
    content = file_path.read_bytes()

    assert pickle.loads(content) == value

    loaded = storage.load(digest_key)
    assert loaded == value


def test_unauthenticating_storage_can_read_authenticated_data(tmp_path):
    """Test that a storage without a secret key can successfully load data written by an authenticating storage."""
    key = b"D" * 32
    storage_auth = PickleFile.with_pickle(root=tmp_path, secret_key=[key])
    storage_noauth = PickleFile.with_pickle(root=tmp_path, secret_key=[])

    value = {"secure": "data", "id": 12345}
    digest_key = storage_auth.save(value)

    loaded = storage_noauth.load(digest_key)
    assert loaded == value


def test_secure_storage_multiple_keys(tmp_path):
    """Test that storage can verify using a list of keys."""
    key1 = b"1" * 32
    key2 = b"2" * 32
    key3 = b"3" * 32

    storage_auth1 = PickleFile.with_pickle(root=tmp_path, secret_key=[key1])
    storage_auth2 = PickleFile.with_pickle(root=tmp_path, secret_key=[key2])
    storage_multi = PickleFile.with_pickle(
        root=tmp_path, secret_key=[key2, key3, key1]
    )  # Multi-key reader

    value1 = "first"
    value2 = "second"

    digest_key1 = storage_auth1.save(value1)
    digest_key2 = storage_auth2.save(value2)

    # Should successfully load both, even though they were signed by different keys
    assert storage_multi.load(digest_key1) == value1
    assert storage_multi.load(digest_key2) == value2

    # Saving with multi-key should sign with the first key (key2)
    digest_key_multi = storage_multi.save("third")
    assert storage_auth2.load(digest_key_multi) == "third"

    with pytest.raises(KeyError, match="Value present but failed signature check."):
        storage_auth1.load(digest_key_multi)


# --- _normalize_secret_key tests ---

def test_normalize_bytes_wrapped_in_list():
    key = b"A" * 32
    assert _normalize_secret_key(key) == [key]


def test_normalize_str_encoded_to_bytes():
    key = "A" * 32
    assert _normalize_secret_key(key) == [key.encode("utf-8")]


def test_normalize_str_with_colon_delimiter():
    key = "A" * 32 + ":" + "B" * 32
    assert _normalize_secret_key(key) == [
        ("A" * 32).encode("utf-8"),
        ("B" * 32).encode("utf-8"),
    ]


def test_normalize_list_of_str():
    keys = ["A" * 32, "B" * 32]
    assert _normalize_secret_key(keys) == [k.encode("utf-8") for k in keys]


def test_normalize_list_of_bytes():
    keys = [b"A" * 32, b"B" * 32]
    assert _normalize_secret_key(keys) == keys


def test_normalize_list_str_with_delimiter():
    keys = ["A" * 32 + ":" + "B" * 32]
    assert _normalize_secret_key(keys) == [
        ("A" * 32).encode("utf-8"),
        ("B" * 32).encode("utf-8"),
    ]


def test_normalize_bytes_too_short_raises():
    with pytest.raises(ValueError, match="at least 32 bytes"):
        _normalize_secret_key(b"short")


def test_normalize_str_too_short_raises():
    with pytest.raises(ValueError, match="at least 32 bytes"):
        _normalize_secret_key("short")


def test_normalize_wrong_type_raises():
    with pytest.raises(TypeError, match="secret_key must be bytes, str, or list"):
        _normalize_secret_key(12345)


def test_normalize_list_wrong_element_type_raises():
    with pytest.raises(TypeError, match="Each element of secret_key must be bytes or str"):
        _normalize_secret_key([12345])


def test_normalize_empty_list_returns_empty():
    # Empty list means security disabled — no normalization needed
    assert _normalize_secret_key([]) == []
