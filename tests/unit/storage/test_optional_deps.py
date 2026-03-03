import sys
import pytest
from unittest.mock import patch
import importlib
import fleche.storage.pickle_file
import fleche.storage.bagofholding_file
import fleche.storage.sql


def test_cloudpickle_missing():
    # Force reload without dependency
    with patch.dict(sys.modules, {"cloudpickle": None}):
        importlib.reload(fleche.storage.pickle_file)
        from fleche.storage.pickle_file import CloudpickleFile

        with pytest.raises(ImportError, match="CloudpickleFile requires"):
            CloudpickleFile("dummy")


def test_bagofholding_missing():
    with patch.dict(sys.modules, {"bagofholding": None}):
        importlib.reload(fleche.storage.bagofholding_file)
        from fleche.storage.bagofholding_file import BagOfHoldingH5File

        with pytest.raises(ImportError, match="BagOfHoldingH5File requires"):
            BagOfHoldingH5File("dummy")


def test_sqlalchemy_missing():
    with patch.dict(
        sys.modules,
        {
            "sqlalchemy": None,
            "sqlalchemy.engine": None,
            "sqlalchemy.orm": None,
            "sqlalchemy.types": None,
        },
    ):
        importlib.reload(fleche.storage.sql)
        from fleche.storage.sql import Sql

        with pytest.raises(ImportError, match="Sql requires"):
            Sql("sqlite:///:memory:")
