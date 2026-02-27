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

    # Modify the data part (after signature)
    # Let's append garbage to the end, which changes the data and should invalidate the signature
    tampered_content = content + b"garbage"
    file_path.write_bytes(tampered_content)

    with pytest.raises(KeyError):
        storage.load(digest_key)

@pytest.mark.parametrize("storage_cls", [PickleFile, CloudpickleFile])
def test_secure_storage_unsigned_data(tmp_path, storage_cls):
    """Test that unsigned data (too short or missing signature) raises KeyError."""
    key = b"B" * 32
    storage = storage_cls(root=tmp_path, secret_key=key)

    value = "test"
    digest_key = digest(value)
    file_path = tmp_path / digest_key

    # Write raw pickle data without signature
    file_path.write_bytes(pickle.dumps(value))

    with pytest.raises(KeyError):
        storage.load(digest_key)

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
    with pytest.raises(KeyError):
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

    # Verify file content is NOT signed (just the pickle)
    file_path = tmp_path / digest_key
    content = file_path.read_bytes()

    # Since we can load it directly with pickle, it means cloudpickle uses the same protocol/format internally
    # and no signature is present.
    assert pickle.loads(content) == value

    loaded = storage.load(digest_key)
    assert loaded == value
