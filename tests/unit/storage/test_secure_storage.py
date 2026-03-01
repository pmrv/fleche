import pickle
import pytest
from pathlib import Path
from fleche.storage.pickle_file import PickleFile
from fleche.storage.cloudpickle_file import CloudpickleFile
from fleche.digest import digest

@pytest.mark.parametrize("storage_cls", [PickleFile, CloudpickleFile])
def test_secure_storage_tampering(tmp_path, storage_cls):
    """Test that tampering with the file content raises KeyError."""
    key = b"A" * 32
    storage = storage_cls(root=tmp_path, secret_key=key)

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

@pytest.mark.parametrize("storage_cls", [PickleFile, CloudpickleFile])
def test_secure_storage_unsigned_data_loads(tmp_path, storage_cls):
    """Test that unsigned data (whether short or long) is loaded without signature check but with a warning."""
    # First, write unsigned data (no secret key)
    storage_noauth = storage_cls(root=tmp_path, secret_key=None)
    value_short = "test"
    value_long = "A" * 100

    digest_short = storage_noauth.save(value_short)
    digest_long = storage_noauth.save(value_long)

    # Now try to read it with an authenticated storage
    key = b"B" * 32
    storage_auth = storage_cls(root=tmp_path, secret_key=key)

    # Should load successfully (it parses STOP opcode and finds no signature)
    assert storage_auth.load(digest_short) == value_short
    assert storage_auth.load(digest_long) == value_long

@pytest.mark.parametrize("storage_cls", [PickleFile, CloudpickleFile])
def test_secure_storage_wrong_key(tmp_path, storage_cls):
    """Test that data signed with a different key cannot be loaded."""
    key1 = b"1" * 32
    key2 = b"2" * 32

    storage1 = storage_cls(root=tmp_path, secret_key=key1)
    storage2 = storage_cls(root=tmp_path, secret_key=key2)

    value = "secret"
    digest_key = storage1.save(value)

    # Try to load with wrong key
    with pytest.raises(KeyError, match="Value present but failed signature check."):
        storage2.load(digest_key)

@pytest.mark.parametrize("storage_cls", [PickleFile, CloudpickleFile])
def test_secure_storage_roundtrip(tmp_path, storage_cls):
    """Test normal save/load operation."""
    key = b"C" * 32
    storage = storage_cls(root=tmp_path, secret_key=key)

    value = [1, 2, 3]
    digest_key = storage.save(value)
    loaded = storage.load(digest_key)

    assert loaded == value

@pytest.mark.parametrize("storage_cls", [PickleFile, CloudpickleFile])
def test_storage_noop_no_key(tmp_path, storage_cls):
    """Test that storage works as normal (unsigned) when no key is provided."""
    storage = storage_cls(root=tmp_path, secret_key=None)

    value = "insecure data"
    digest_key = storage.save(value)

    file_path = tmp_path / digest_key
    content = file_path.read_bytes()

    assert pickle.loads(content) == value

    loaded = storage.load(digest_key)
    assert loaded == value

@pytest.mark.parametrize("storage_cls", [PickleFile, CloudpickleFile])
def test_unauthenticating_storage_can_read_authenticated_data(tmp_path, storage_cls):
    """Test that a storage without a secret key can successfully load data written by an authenticating storage."""
    key = b"D" * 32
    storage_auth = storage_cls(root=tmp_path, secret_key=key)
    storage_noauth = storage_cls(root=tmp_path, secret_key=None)

    value = {"secure": "data", "id": 12345}
    digest_key = storage_auth.save(value)

    loaded = storage_noauth.load(digest_key)
    assert loaded == value

@pytest.mark.parametrize("storage_cls", [PickleFile, CloudpickleFile])
def test_secure_storage_multiple_keys(tmp_path, storage_cls):
    """Test that storage can verify using a list of keys."""
    key1 = b"1" * 32
    key2 = b"2" * 32
    key3 = b"3" * 32

    storage_auth1 = storage_cls(root=tmp_path, secret_key=key1)
    storage_auth2 = storage_cls(root=tmp_path, secret_key=key2)
    storage_multi = storage_cls(root=tmp_path, secret_key=[key2, key3, key1]) # Multi-key reader

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
