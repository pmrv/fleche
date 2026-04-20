import pytest
from fleche.storage.pickle_file import ValuePickleFile as PickleFile
from fleche.digest import Digest


def test_load_file_not_found(tmp_path):
    """
    Test that PickleFile._load raises KeyError when the file is not found.
    This triggers the FileNotFoundError exception path in _load.
    """
    storage = PickleFile.with_pickle(root=tmp_path)
    # Use a valid full-length digest key that doesn't exist in the storage
    non_existent_key = Digest("a" * 64)

    # Verify that attempting to load a non-existent file raises KeyError
    # We call get directly to bypass expansion/lock logic and target the specific code path
    with pytest.raises(KeyError) as exc_info:
        storage.get(non_existent_key)

    # Ensure the correct path is in the exception
    assert str(storage._path(non_existent_key)) in str(exc_info.value)


def test_compression(tmp_path):
    """
    Test that PickleFile with compress=True correctly compresses data.
    """
    storage = PickleFile.with_pickle(root=tmp_path, compress=True)
    value = {"a": 1, "b": 2}
    key = Digest("a" * 64)

    # Save the value
    storage.put(value, key)

    # Check if the file is compressed
    content = (tmp_path / str(key)).read_bytes()
    # Gzip magic number is 0x1f 0x8b
    assert content.startswith(b"\x1f\x8b")

    # Load the value
    loaded_value = storage.get(key)
    assert loaded_value == value


# --- PickleFile.__post_init__ key handling tests ---

def test_post_init_bytes_key(tmp_path):
    key = b"A" * 32
    storage = PickleFile.with_pickle(root=tmp_path, secret_key=key)
    assert storage.secret_key == (key,)


def test_post_init_str_key(tmp_path):
    key = "ab" * 32  # valid 64-char hex string
    storage = PickleFile.with_pickle(root=tmp_path, secret_key=key)
    assert storage.secret_key == (bytes.fromhex(key),)


def test_post_init_str_key_with_delimiter(tmp_path):
    k1, k2 = "ab" * 16, "cd" * 16
    key = k1 + ":" + k2
    storage = PickleFile.with_pickle(root=tmp_path, secret_key=key)
    assert storage.secret_key == (bytes.fromhex(k1), bytes.fromhex(k2))


def test_post_init_wrong_key_type_raises(tmp_path):
    with pytest.raises(TypeError):
        PickleFile.with_pickle(root=tmp_path, secret_key=42)


def test_post_init_str_key_roundtrip(tmp_path):
    key = "ab" * 32  # valid 64-char hex string
    storage = PickleFile.with_pickle(root=tmp_path, secret_key=key)
    value = {"hello": "world"}
    digest_key = storage.save(value)
    assert storage.load(digest_key) == value
