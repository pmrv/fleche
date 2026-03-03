import pytest

from fleche.storage.bagofholding_file import BagOfHoldingH5File


def test_load_corrupt_h5_file(tmp_path):
    storage = BagOfHoldingH5File(str(tmp_path))

    key = "corrupt_key"
    path = storage._path(key)
    path.parent.mkdir(parents=True, exist_ok=True)

    # Write corrupt/invalid HDF5 file
    path.write_bytes(b"this is not a valid hdf5 file")

    with pytest.raises(OSError):
        storage._load(key)
