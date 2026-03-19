import pytest
from fleche.storage.pickle_file import PickleFile
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

    # Ensure the correct key is in the exception
    assert str(exc_info.value) == f"'{non_existent_key}'"


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
