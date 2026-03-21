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

    assert f"Corrupt file present in cache for key {key}" in caplog.text


def test_nested_dict_digest_keys(tmp_path):
    from fleche.digest import Digest
    storage = BagOfHoldingH5File(str(tmp_path))

    val = {Digest("a"): {Digest("b"): Digest("c")}}
    key = Digest("nested_key")

    storage.save(val, key)
    loaded = storage.load(key)

    assert val == loaded
    assert isinstance(next(iter(loaded.keys())), Digest)
    assert isinstance(next(iter(loaded[Digest("a")].keys())), Digest)
