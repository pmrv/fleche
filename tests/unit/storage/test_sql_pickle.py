import pytest
import pickle
from fleche.storage.sql import Sql


def test_sql_pickles():
    sql = Sql("sqlite:///:memory:")
    pickled = pickle.dumps(sql)
    unpickled = pickle.loads(pickled)
    assert sql == unpickled
