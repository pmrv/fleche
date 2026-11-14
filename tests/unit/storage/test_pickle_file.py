import pickle

import pytest
from fleche.storage.pickle_file import (
    ValuePickleFile as PickleFile,
    CallPickleFile,
    register_serializer,
)
from fleche.digest import Digest


# --- serializer registry tests ---


def test_with_serializer_pickle_matches_with_pickle(tmp_path):
    storage = PickleFile.with_serializer("pickle", root=tmp_path)
    assert storage.serializer == "pickle"
    assert storage.dumps is pickle.dumps
    assert storage.loads is pickle.loads


def test_with_pickle_sets_serializer_field(tmp_path):
    storage = PickleFile.with_pickle(root=tmp_path)
    assert storage.serializer == "pickle"


def test_unknown_serializer_raises(tmp_path):
    with pytest.raises(ValueError, match="Unknown PickleFile serializer 'bogus'"):
        PickleFile.with_serializer("bogus", root=tmp_path)


def test_register_serializer_enables_with_serializer(tmp_path):
    calls = []

    def loader():
        calls.append(1)
        return pickle.dumps, pickle.loads

    register_serializer("my-test-serializer", loader)
    try:
        storage = PickleFile.with_serializer("my-test-serializer", root=tmp_path)
        assert storage.serializer == "my-test-serializer"
        assert calls == [1]  # loader only runs once the serializer is actually selected

        value = {"a": 1}
        key = storage.save(value)
        assert storage.load(key) == value
    finally:
        from fleche.storage.pickle_file import _SERIALIZERS

        del _SERIALIZERS["my-test-serializer"]


def test_to_config_type_reflects_serializer_field(tmp_path):
    storage = PickleFile.with_pickle(root=tmp_path)
    assert storage.to_config()["type"] == "pickle"


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


def test_read_compressed_file_with_compress_false(tmp_path):
    """A storage with compress=False can still read files written with compress=True."""
    writer = PickleFile.with_pickle(root=tmp_path, compress=True)
    reader = PickleFile.with_pickle(root=tmp_path, compress=False)
    value = {"x": 42}
    key = writer.save(value)
    assert reader.load(key) == value


def test_read_uncompressed_file_with_compress_true(tmp_path):
    """A storage with compress=True can still read files written with compress=False."""
    writer = PickleFile.with_pickle(root=tmp_path, compress=False)
    reader = PickleFile.with_pickle(root=tmp_path, compress=True)
    value = {"x": 42}
    key = writer.save(value)
    assert reader.load(key) == value


def test_compress_all(tmp_path):
    """compress_all() rewrites uncompressed files as gzip-compressed."""
    storage = PickleFile.with_pickle(root=tmp_path, compress=False)
    value = {"a": 1}
    key = storage.save(value)

    raw = (tmp_path / str(key)).read_bytes()
    assert raw[:2] != b"\x1f\x8b"

    storage.compress_all()

    raw = (tmp_path / str(key)).read_bytes()
    assert raw[:2] == b"\x1f\x8b"
    assert storage.load(key) == value


def test_compress_all_idempotent(tmp_path):
    """compress_all() on already-compressed files leaves them unchanged."""
    storage = PickleFile.with_pickle(root=tmp_path, compress=True)
    value = {"a": 1}
    key = storage.save(value)

    storage.compress_all()
    storage.compress_all()

    assert storage.load(key) == value


def test_decompress_all(tmp_path):
    """decompress_all() rewrites gzip-compressed files as uncompressed."""
    storage = PickleFile.with_pickle(root=tmp_path, compress=True)
    value = {"a": 1}
    key = storage.save(value)

    raw = (tmp_path / str(key)).read_bytes()
    assert raw[:2] == b"\x1f\x8b"

    storage.decompress_all()

    raw = (tmp_path / str(key)).read_bytes()
    assert raw[:2] != b"\x1f\x8b"
    assert storage.load(key) == value


def test_decompress_all_idempotent(tmp_path):
    """decompress_all() on already-uncompressed files leaves them unchanged."""
    storage = PickleFile.with_pickle(root=tmp_path, compress=False)
    value = {"a": 1}
    key = storage.save(value)

    storage.decompress_all()
    storage.decompress_all()

    assert storage.load(key) == value


def test_compress_then_decompress_roundtrip(tmp_path):
    """compress_all() followed by decompress_all() preserves values."""
    storage = PickleFile.with_pickle(root=tmp_path, compress=False)
    values = {storage.save({"n": i}): {"n": i} for i in range(5)}

    storage.compress_all()
    storage.decompress_all()

    for key, value in values.items():
        assert storage.load(key) == value


def test_rewrite_all_custom_transform(tmp_path):
    """_rewrite_all() applies an arbitrary byte transform to every file."""
    # Use CallPickleFile (no DestructuringMixin) so exactly one file is created.
    storage = CallPickleFile.with_pickle(root=tmp_path, compress=False)
    key = Digest("a" * 64)
    value = {"x": 1}
    storage.put(value, key)
    original = (tmp_path / str(key)).read_bytes()

    seen = []
    storage._rewrite_all(lambda c: seen.append(c) or None)

    assert seen == [original]
    assert (tmp_path / str(key)).read_bytes() == original  # file unchanged when None returned


def test_rewrite_all_skips_missing_files(tmp_path):
    """_rewrite_all() silently skips files deleted between list() and read."""
    storage = CallPickleFile.with_pickle(root=tmp_path, compress=False)
    key = Digest("a" * 64)
    storage.put({"x": 1}, key)
    (tmp_path / str(key)).unlink()

    called = []
    storage._rewrite_all(lambda c: called.append(c) or None)
    assert called == []
