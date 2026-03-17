import sys
import pytest
from unittest.mock import patch


def _test_missing_dep(module_name: str, deps_to_mock: dict, test_logic: callable):
    # Save and pop the module so the test loads a completely fresh copy
    original_module = sys.modules.pop(module_name, None)

    try:
        with patch.dict(sys.modules, deps_to_mock):
            # This triggers a fresh import of the module without mutating the original
            test_logic()
    finally:
        # Restore the exact original module object so pickling and instanceof checks aren't broken elsewhere
        if original_module:
            sys.modules[module_name] = original_module


def test_cloudpickle_missing():
    def logic():
        import fleche.storage.pickle_file
        from fleche.storage.pickle_file import PickleFile

        with pytest.raises(ImportError, match="PickleFile.with_cloudpickle requires"):
            PickleFile.with_cloudpickle("dummy")

    _test_missing_dep("fleche.storage.pickle_file", {"cloudpickle": None}, logic)


def test_dill_missing():
    def logic():
        import fleche.storage.pickle_file
        from fleche.storage.pickle_file import PickleFile

        with pytest.raises(ImportError, match="PickleFile.with_dill requires"):
            PickleFile.with_dill("dummy")

    _test_missing_dep("fleche.storage.pickle_file", {"dill": None}, logic)


def test_bagofholding_missing():
    def logic():
        import fleche.storage.bagofholding_file
        from fleche.storage.bagofholding_file import BagOfHoldingH5File

        with pytest.raises(ImportError, match="BagOfHoldingH5File requires"):
            BagOfHoldingH5File("dummy")

    _test_missing_dep("fleche.storage.bagofholding_file", {"bagofholding": None}, logic)


def test_sqlalchemy_missing():
    def logic():
        import fleche.storage.sql
        from fleche.storage.sql import Sql

        with pytest.raises(ImportError, match="Sql requires"):
            Sql("sqlite:///:memory:")

    _test_missing_dep(
        "fleche.storage.sql",
        {
            "sqlalchemy": None,
            "sqlalchemy.engine": None,
            "sqlalchemy.orm": None,
            "sqlalchemy.types": None,
        },
        logic,
    )
