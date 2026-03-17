import pytest
import pickle
import importlib
import sys

# Force a reload of the storage SQL module to prevent pickling issues
# when pytest executes test_optional_deps.py earlier which reloads the module and orphans the class.
if "fleche.storage.sql" in sys.modules:
    importlib.reload(sys.modules["fleche.storage.sql"])

from fleche.storage.sql import Sql


def test_sql_pickles():
    sql = Sql("sqlite:///:memory:")
    pickled = pickle.dumps(sql)
    unpickled = pickle.loads(pickled)
    assert sql == unpickled
