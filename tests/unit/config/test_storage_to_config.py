import tempfile
from pathlib import Path

import pytest

from fleche import storage
from fleche.config import storage_to_config, _get_storage


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


def test_destructuring_storage_nested():
    inner = storage.DestructuringStorage(storage.Memory({}))
    s = storage.DestructuringStorage(inner)
    cfg = storage_to_config(s)
    assert cfg == {
        "type": "DestructuringStorage",
        "storage": {
            "type": "DestructuringStorage",
            "storage": {"type": "Memory"},
        },
    }


def test_pickle_file():
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir) / "values"
        s = storage.PickleFile.with_pickle(root=root)
        cfg = storage_to_config(s)
        assert cfg["type"] == "PickleFile"
        assert cfg["root"] == str(s.root)


def test_cloudpickle_file():
    pytest.importorskip("cloudpickle")
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir) / "values"
        s = storage.PickleFile.with_cloudpickle(root=root)
        cfg = storage_to_config(s)
        assert cfg["type"] == "CloudpickleFile"
        assert cfg["root"] == str(s.root)


def test_dill_file():
    pytest.importorskip("dill")
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir) / "values"
        s = storage.PickleFile.with_dill(root=root)
        cfg = storage_to_config(s)
        assert cfg["type"] == "DillFile"
        assert cfg["root"] == str(s.root)


def test_bagofholding_h5file():
    pytest.importorskip("bagofholding")
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir) / "values"
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
        def _save(self, value, key):
            return key

        def _load(self, key):
            raise KeyError(key)

        def list(self):
            return ()

        def _evict(self, key):
            pass

    with pytest.raises(ValueError, match="CustomStorage"):
        storage_to_config(CustomStorage())


def test_roundtrip_memory():
    cfg = {"type": "Memory"}
    s = _get_storage(cfg.copy())
    assert isinstance(s, storage.Memory)
    assert storage_to_config(s) == {"type": "Memory"}


def test_roundtrip_void():
    cfg = {"type": "Void"}
    s = _get_storage(cfg.copy())
    assert isinstance(s, storage.Void)
    assert storage_to_config(s) == {"type": "Void"}


def test_roundtrip_destructuring_memory():
    cfg = {"type": "DestructuringStorage", "storage": {"type": "Memory"}}
    s = _get_storage(cfg.copy())
    assert isinstance(s, storage.DestructuringStorage)
    assert isinstance(s.storage, storage.Memory)
    result = storage_to_config(s)
    assert result == {"type": "DestructuringStorage", "storage": {"type": "Memory"}}


def test_roundtrip_pickle_file():
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir) / "values"
        original = storage.PickleFile.with_pickle(root=root)
        cfg = storage_to_config(original)
        reconstructed = _get_storage(cfg)
        assert isinstance(reconstructed, storage.PickleFile)
        assert reconstructed.root == original.root
