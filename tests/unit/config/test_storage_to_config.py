
import pytest

from fleche import storage
from fleche.config import storage_to_config, storage_from_config


def test_memory():
    s = storage.ValueMemory({})
    assert storage_to_config(s) == {"type": "memory", "remaining_depth": 0}


def test_void():
    s = storage.ValueVoid()
    assert storage_to_config(s) == {"type": "void"}


def test_pickle_file(tmp_path):
    root = tmp_path / "values"
    s = storage.ValuePickleFile.with_pickle(root=root)
    cfg = storage_to_config(s)
    assert cfg["type"] == "pickle"
    assert cfg["root"] == str(s.root)


def test_dill_file(tmp_path):
    pytest.importorskip("dill")
    root = tmp_path / "values"
    s = storage.ValuePickleFile.with_dill(root=root)
    cfg = storage_to_config(s)
    assert cfg["type"] == "dill"
    assert cfg["root"] == str(s.root)


def test_bagofholding_h5file(tmp_path):
    pytest.importorskip("bagofholding")
    root = tmp_path / "values"
    s = storage.ValueBagOfHoldingH5File(root=root)
    cfg = storage_to_config(s)
    assert cfg["type"] == "bagofholding_hdf"
    assert cfg["root"] == str(s.root)
    assert cfg["version_validator"] is None


def test_bagofholding_h5file_with_version_validator(tmp_path):
    pytest.importorskip("bagofholding")
    root = tmp_path / "values"
    s = storage.ValueBagOfHoldingH5File(root=root, version_validator="none")
    cfg = storage_to_config(s)
    assert cfg["type"] == "bagofholding_hdf"
    assert cfg["version_validator"] == "none"


def test_bagofholding_h5file_version_validator_roundtrip(tmp_path):
    pytest.importorskip("bagofholding")
    root = tmp_path / "values"
    original = storage.ValueBagOfHoldingH5File(root=root, version_validator="semantic-minor")
    cfg = storage_to_config(original)
    reconstructed = storage_from_config(cfg, "value")
    assert isinstance(reconstructed, storage.ValueBagOfHoldingH5File)
    assert reconstructed.version_validator == "semantic-minor"


def test_sql():
    pytest.importorskip("sqlalchemy")
    s = storage.Sql(url="sqlite:///:memory:")
    cfg = storage_to_config(s)
    assert cfg["type"] == "sql"
    assert cfg["url"] == s.url


def test_unknown_storage_raises():
    class CustomStorage(storage.ValueStorage):
        def put(self, value, key): return key
        def get(self, key): raise KeyError(key)
        def list(self): return ()
        def _evict(self, key): pass
        def _contains(self, key): return False
        def save(self, value, key=None): pass
        def load(self, key): raise KeyError(key)

    with pytest.raises(ValueError, match="CustomStorage"):
        storage_to_config(CustomStorage())


def test_roundtrip_memory():
    cfg = {"type": "memory"}
    s = storage_from_config(cfg, "value")
    assert isinstance(s, storage.ValueMemory)
    assert storage_to_config(s) == {"type": "memory", "remaining_depth": 0}


def test_roundtrip_void():
    cfg = {"type": "void"}
    s = storage_from_config(cfg, "value")
    assert isinstance(s, storage.ValueVoid)
    assert storage_to_config(s) == {"type": "void"}


def test_roundtrip_pickle_file(tmp_path):
    root = tmp_path / "values"
    original = storage.ValuePickleFile.with_pickle(root=root)
    cfg = storage_to_config(original)
    reconstructed = storage_from_config(cfg, "value")
    assert isinstance(reconstructed, storage.ValuePickleFile)
    assert reconstructed.root == original.root


def test_roundtrip_pickle_file_with_secret_key(tmp_path):
    root = tmp_path / "values"
    key = bytes.fromhex("ab" * 32)
    original = storage.ValuePickleFile.with_pickle(root=root, secret_key=[key])
    cfg = storage_to_config(original)
    assert cfg["secret_key"] == [("ab" * 32)]
    reconstructed = storage_from_config(cfg, "value")
    assert isinstance(reconstructed, storage.ValuePickleFile)
    assert reconstructed.secret_key == [key]


def test_pickle_file_no_secret_key_omitted_from_config(tmp_path):
    root = tmp_path / "values"
    original = storage.ValuePickleFile.with_pickle(root=root, secret_key=[])
    cfg = storage_to_config(original)
    assert "secret_key" not in cfg


def test_storage_from_config_does_not_mutate():
    cfg = {"type": "memory"}
    storage_from_config(cfg, "value")
    assert cfg == {"type": "memory"}


def test_storage_from_config_unknown_type():
    with pytest.raises(ValueError, match="UnknownType"):
        storage_from_config({"type": "UnknownType"}, "value")
