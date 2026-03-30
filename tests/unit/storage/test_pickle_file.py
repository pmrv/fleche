import pytest
from fleche.storage.pickle_file import PickleFile, _normalize_secret_key
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
    # We call _load directly to bypass expansion/lock logic and target the specific code path
    with pytest.raises(KeyError) as exc_info:
        storage._load(non_existent_key)

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
    storage._save(value, key)

    # Check if the file is compressed
    content = (tmp_path / str(key)).read_bytes()
    # Gzip magic number is 0x1f 0x8b
    assert content.startswith(b"\x1f\x8b")

    # Load the value
    loaded_value = storage._load(key)
    assert loaded_value == value


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


# --- PickleFile.__post_init__ key handling tests ---

def test_post_init_bytes_key(tmp_path):
    key = b"A" * 32
    storage = PickleFile.with_pickle(root=tmp_path, secret_key=key)
    assert storage.secret_key == [key]


def test_post_init_str_key(tmp_path):
    key = "A" * 32
    storage = PickleFile.with_pickle(root=tmp_path, secret_key=key)
    assert storage.secret_key == [key.encode("utf-8")]


def test_post_init_str_key_with_delimiter(tmp_path):
    key = "A" * 32 + ":" + "B" * 32
    storage = PickleFile.with_pickle(root=tmp_path, secret_key=key)
    assert storage.secret_key == [
        ("A" * 32).encode("utf-8"),
        ("B" * 32).encode("utf-8"),
    ]


def test_post_init_short_key_raises(tmp_path):
    with pytest.raises(ValueError, match="at least 32 bytes"):
        PickleFile.with_pickle(root=tmp_path, secret_key=b"tooshort")


def test_post_init_wrong_key_type_raises(tmp_path):
    with pytest.raises(TypeError):
        PickleFile.with_pickle(root=tmp_path, secret_key=42)


def test_post_init_str_key_roundtrip(tmp_path):
    key = "A" * 32
    storage = PickleFile.with_pickle(root=tmp_path, secret_key=key)
    value = {"hello": "world"}
    digest_key = storage.save(value)
    assert storage.load(digest_key) == value
