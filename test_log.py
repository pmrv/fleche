import pytest
import logging
from fleche.storage.bagofholding_file import BagOfHoldingH5File

def test_load_corrupt_h5_file_logs(tmp_path, caplog):
    storage = BagOfHoldingH5File(str(tmp_path))
    key = "corrupt_key"
    path = storage._path(key)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"invalid data")

    with caplog.at_level(logging.ERROR, logger="fleche.storage.bagofholding_file"):
        with pytest.raises(KeyError):
            storage._load(key)

    assert "Corrupt file present in cache for key corrupt_key" in caplog.text
