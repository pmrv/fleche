import logging
import pytest

from fleche.digest import Digest
from fleche.storage.bagofholding_file import BagOfHoldingH5FileBackend


def test_load_corrupt_h5_file(tmp_path, caplog):
    storage = BagOfHoldingH5FileBackend(tmp_path)

    key = Digest("corrupt_key")
    path = storage._path(key)
    path.parent.mkdir(parents=True, exist_ok=True)

    # Write corrupt/invalid HDF5 file
    path.write_bytes(b"this is not a valid hdf5 file")

    with caplog.at_level(logging.ERROR, logger="fleche.storage.bagofholding_file"):
        with pytest.raises(KeyError):
            storage.get(key)

    assert f"Corrupt file present in cache at path {path}" in caplog.text


def test_version_validator_default_is_none(tmp_path):
    pytest.importorskip("bagofholding")
    s = BagOfHoldingH5FileBackend(tmp_path)
    assert s.version_validator is None


def test_version_validator_field_accepted(tmp_path):
    pytest.importorskip("bagofholding")
    s = BagOfHoldingH5FileBackend(tmp_path, version_validator="none")
    assert s.version_validator == "none"


def test_version_validator_passed_to_load(tmp_path, monkeypatch):
    pytest.importorskip("bagofholding")
    import fleche.storage.bagofholding_file as boh_mod

    captured = {}

    class FakeH5Bag:
        def __init__(self, path):
            self.path = path

        def load(self, **kwargs):
            captured.update(kwargs)
            return 42

        @staticmethod
        def save(value, path):
            pass

    monkeypatch.setattr(boh_mod, "H5Bag", FakeH5Bag)

    s = BagOfHoldingH5FileBackend(tmp_path, version_validator="semantic-minor")
    key = Digest("test_key")
    s.put(42, key)
    result = s.get(key)

    assert result == 42
    assert captured.get("version_validator") == "semantic-minor"


def test_version_validator_none_not_passed_to_load(tmp_path, monkeypatch):
    pytest.importorskip("bagofholding")
    import fleche.storage.bagofholding_file as boh_mod

    captured = {"called": False}

    class FakeH5Bag:
        def __init__(self, path):
            self.path = path

        def load(self, **kwargs):
            captured["kwargs"] = kwargs
            captured["called"] = True
            return 42

        @staticmethod
        def save(value, path):
            pass

    monkeypatch.setattr(boh_mod, "H5Bag", FakeH5Bag)

    s = BagOfHoldingH5FileBackend(tmp_path)
    key = Digest("test_key2")
    s.put(42, key)
    s.get(key)

    assert captured["called"]
    assert "version_validator" not in captured["kwargs"]
