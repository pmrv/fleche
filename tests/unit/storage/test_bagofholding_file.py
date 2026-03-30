import logging
import pytest

from fleche.storage.bagofholding_file import BagOfHoldingH5File


def test_load_corrupt_h5_file(tmp_path, caplog):
    storage = BagOfHoldingH5File(str(tmp_path))

    key = "corrupt_key"
    path = storage._path(key)
    path.parent.mkdir(parents=True, exist_ok=True)

    # Write corrupt/invalid HDF5 file
    path.write_bytes(b"this is not a valid hdf5 file")

    with caplog.at_level(logging.ERROR, logger="fleche.storage.bagofholding_file"):
        with pytest.raises(KeyError):
            storage._load(key)

    assert f"Corrupt file present in cache at path {path}" in caplog.text
