import logging
from unittest.mock import MagicMock

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

    mock_h5bag = MagicMock()
    mock_h5bag.return_value.load.return_value = 42
    monkeypatch.setattr(boh_mod, "H5Bag", mock_h5bag)

    s = BagOfHoldingH5FileBackend(tmp_path, version_validator="semantic-minor")
    key = Digest("test_key")
    s.put(42, key)
    result = s.get(key)

    assert result == 42
    mock_h5bag.return_value.load.assert_called_with(version_validator="semantic-minor")


def test_version_validator_none_not_passed_to_load(tmp_path, monkeypatch):
    pytest.importorskip("bagofholding")
    import fleche.storage.bagofholding_file as boh_mod

    mock_h5bag = MagicMock()
    mock_h5bag.return_value.load.return_value = 42
    monkeypatch.setattr(boh_mod, "H5Bag", mock_h5bag)

    s = BagOfHoldingH5FileBackend(tmp_path)
    key = Digest("test_key2")
    s.put(42, key)
    s.get(key)

    _, kwargs = mock_h5bag.return_value.load.call_args
    assert "version_validator" not in kwargs


def test_rebag_calls_load_and_save(tmp_path, monkeypatch):
    pytest.importorskip("bagofholding")
    import fleche.storage.bagofholding_file as boh_mod

    mock_h5bag = MagicMock()
    mock_h5bag.return_value.load.return_value = 99
    monkeypatch.setattr(boh_mod, "H5Bag", mock_h5bag)

    s = BagOfHoldingH5FileBackend(tmp_path)
    key = Digest("resave_key")
    s._path(key).write_bytes(b"dummy")

    s.rebag(version_validator="none")

    mock_h5bag.return_value.load.assert_called_once_with(version_validator="none")
    mock_h5bag.save.assert_called_once_with(99, s._path(key))


def test_rebag_skips_oserror(tmp_path, monkeypatch, caplog):
    pytest.importorskip("bagofholding")
    import fleche.storage.bagofholding_file as boh_mod

    mock_h5bag = MagicMock()
    mock_h5bag.return_value.load.side_effect = OSError("broken bag")
    monkeypatch.setattr(boh_mod, "H5Bag", mock_h5bag)

    s = BagOfHoldingH5FileBackend(tmp_path)
    key = Digest("broken_key")
    s._path(key).write_bytes(b"dummy")

    with caplog.at_level(logging.WARNING, logger="fleche.storage.bagofholding_file"):
        s.rebag(version_validator="none")  # should not raise

    assert "Failed to rebag" in caplog.text


def test_from_file_passes_skip_load_to_h5bag(tmp_path, monkeypatch):
    """_from_file must pass _skip_load=True so the file is opened only once per get."""
    pytest.importorskip("bagofholding")
    import fleche.storage.bagofholding_file as boh_mod

    mock_h5bag = MagicMock()
    mock_h5bag.return_value.load.return_value = 7
    monkeypatch.setattr(boh_mod, "H5Bag", mock_h5bag)

    s = BagOfHoldingH5FileBackend(tmp_path)
    key = Digest("skip_load_key")
    s.get(key)

    _, kwargs = mock_h5bag.call_args
    assert kwargs.get("_skip_load") is True


def test_rebag_passes_skip_load_to_h5bag(tmp_path, monkeypatch):
    """rebag must pass _skip_load=True so the file is opened only once per entry."""
    pytest.importorskip("bagofholding")
    import fleche.storage.bagofholding_file as boh_mod

    mock_h5bag = MagicMock()
    mock_h5bag.return_value.load.return_value = 1
    monkeypatch.setattr(boh_mod, "H5Bag", mock_h5bag)

    s = BagOfHoldingH5FileBackend(tmp_path)
    key = Digest("rebag_skip_load_key")
    s._path(key).write_bytes(b"dummy")

    s.rebag()

    _, kwargs = mock_h5bag.call_args
    assert kwargs.get("_skip_load") is True


def test_rebag_default_validator_is_none(tmp_path, monkeypatch):
    pytest.importorskip("bagofholding")
    import fleche.storage.bagofholding_file as boh_mod

    mock_h5bag = MagicMock()
    mock_h5bag.return_value.load.return_value = 1
    monkeypatch.setattr(boh_mod, "H5Bag", mock_h5bag)

    s = BagOfHoldingH5FileBackend(tmp_path)
    key = Digest("default_key")
    s._path(key).write_bytes(b"dummy")

    s.rebag()

    mock_h5bag.return_value.load.assert_called_once_with(version_validator="none")
