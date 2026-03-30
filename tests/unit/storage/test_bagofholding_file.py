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
