
import pytest

from fleche import storage
from fleche.config import storage_to_config, storage_from_config


def test_memory():
    s = storage.Memory({})
    assert storage_to_config(s) == {"type": "Memory"}


def test_void():
    s = storage.Void()
    assert storage_to_config(s) == {"type": "Void"}


def test_destructuring_storage_wrapping_memory():
    s = storage.DestructuringStorage(storage.Memory({}))
    cfg = storage_to_config(s)
    assert cfg == {"type": "DestructuringStorage", "storage": {"type": "Memory"}}


def test_destructuring_storage_no_nesting():
    inner = storage.DestructuringStorage(storage.Memory({}))
    with pytest.raises(ValueError, match="DestructuringStorage"):
        storage.DestructuringStorage(inner)


def test_pickle_file(tmp_path):
    root = tmp_path / "values"
    s = storage.PickleFile.with_pickle(root=root)
    cfg = storage_to_config(s)
    assert cfg["type"] == "PickleFile"
    assert cfg["root"] == str(s.root)


def test_cloudpickle_file(tmp_path):
    pytest.importorskip("cloudpickle")
    root = tmp_path / "values"
    s = storage.PickleFile.with_cloudpickle(root=root)
    cfg = storage_to_config(s)
    assert cfg["type"] == "CloudpickleFile"
    assert cfg["root"] == str(s.root)


def test_dill_file(tmp_path):
    pytest.importorskip("dill")
    root = tmp_path / "values"
    s = storage.PickleFile.with_dill(root=root)
    cfg = storage_to_config(s)
    assert cfg["type"] == "DillFile"
    assert cfg["root"] == str(s.root)


def test_bagofholding_h5file(tmp_path):
    pytest.importorskip("bagofholding")
    root = tmp_path / "values"
    s = storage.BagOfHoldingH5File(root=root)
    cfg = storage_to_config(s)
    assert cfg["type"] == "BagOfHoldingH5File"
    assert cfg["root"] == str(s.root)


def test_sql():
    pytest.importorskip("sqlalchemy")
    s = storage.Sql(url="sqlite:///:memory:")
    cfg = storage_to_config(s)
    assert cfg["type"] == "Sql"
    assert cfg["url"] == s.url


def test_unknown_storage_raises():
    class CustomStorage(storage.Storage):
        def put(self, value, key):
            return key

        def get(self, key):
            raise KeyError(key)

        def list(self):
            return ()

        def pop(self, key):
            pass

    with pytest.raises(ValueError, match="CustomStorage"):
        storage_to_config(CustomStorage())


def test_roundtrip_memory():
    cfg = {"type": "Memory"}
    s = storage_from_config(cfg)
    assert isinstance(s, storage.Memory)
    assert storage_to_config(s) == {"type": "Memory"}


def test_roundtrip_void():
    cfg = {"type": "Void"}
    s = storage_from_config(cfg)
    assert isinstance(s, storage.Void)
    assert storage_to_config(s) == {"type": "Void"}


def test_roundtrip_destructuring_memory():
    cfg = {"type": "DestructuringStorage", "storage": {"type": "Memory"}}
    s = storage_from_config(cfg)
    assert isinstance(s, storage.DestructuringStorage)
    assert isinstance(s.storage, storage.Memory)
    result = storage_to_config(s)
    assert result == {"type": "DestructuringStorage", "storage": {"type": "Memory"}}


def test_roundtrip_pickle_file(tmp_path):
    root = tmp_path / "values"
    original = storage.PickleFile.with_pickle(root=root)
    cfg = storage_to_config(original)
    reconstructed = storage_from_config(cfg)
    assert isinstance(reconstructed, storage.PickleFile)
    assert reconstructed.root == original.root


def test_storage_from_config_does_not_mutate():
    cfg = {"type": "Memory"}
    storage_from_config(cfg)
    assert cfg == {"type": "Memory"}


def test_storage_from_config_destructuring_does_not_mutate():
    cfg = {"type": "DestructuringStorage", "storage": {"type": "Memory"}}
    storage_from_config(cfg)
    assert cfg == {"type": "DestructuringStorage", "storage": {"type": "Memory"}}


def test_storage_from_config_unknown_type():
    with pytest.raises(ValueError, match="UnknownType"):
        storage_from_config({"type": "UnknownType"})
