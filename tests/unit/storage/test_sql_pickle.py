import pytest
import pickle
import importlib
import fleche.storage.sql

importlib.reload(fleche.storage.sql)

from dataclasses import is_dataclass


def test_sql_pickles():
    import sys

    if "fleche.storage.sql" in sys.modules:
        import importlib

        importlib.reload(sys.modules["fleche.storage.sql"])
    from fleche.storage.sql import Sql

    sql = Sql("sqlite:///:memory:")
    pickled = pickle.dumps(sql)
    unpickled = pickle.loads(pickled)
    assert sql == unpickled
