"""
Regression test for issue #319: query().table() index doesn't match storage keys in SQL.

Root cause: sql.py get() returned code_digest as a plain str, but at save time it was
a Digest. digest(Digest(x)) == x (identity) but digest(str(x)) == SHA256("str" + x.encode()),
so to_lookup_key() produced different hashes before and after SQL round-trip.
"""

import pytest
from fleche.storage.sql import Sql
from fleche.storage.memory import ValueMemory
from fleche.caches import Cache
from fleche import fleche, cache


def test_sql_load_by_table_index_with_code_digest(tmp_path):
    """cache.load(table().index.iloc[0]) must not raise KeyError in SQL config with hash_code=True."""
    db_path = tmp_path / "calls.db"
    c = Cache(values=ValueMemory(storage={}), calls=Sql(str(db_path)))

    with cache(c):
        @fleche(hash_code=True)
        def my_func(x):
            return x * 2

        my_func(1)
        my_func(2)

        table = c.table()
        assert len(table) == 2

        for key in table.index:
            result = c.load(key)
            assert result is not None


def test_sql_load_by_table_index_without_code_digest(tmp_path):
    """cache.load(table().index.iloc[0]) must not raise KeyError in SQL config with hash_code=False."""
    db_path = tmp_path / "calls.db"
    c = Cache(values=ValueMemory(storage={}), calls=Sql(str(db_path)))

    with cache(c):
        @fleche(hash_code=False)
        def my_func(x):
            return x * 2

        my_func(1)
        my_func(2)

        table = c.table()
        assert len(table) == 2

        for key in table.index:
            result = c.load(key)
            assert result is not None


def test_sql_table_index_matches_storage_keys(tmp_path):
    """table().index values must equal the keys returned by calls.list()."""
    db_path = tmp_path / "calls.db"
    c = Cache(values=ValueMemory(storage={}), calls=Sql(str(db_path)))

    with cache(c):
        @fleche(hash_code=True)
        def my_func(x):
            return x * 2

        my_func(1)
        my_func(2)

    table = c.table(shrink_keys=False)
    storage_keys = set(str(k) for k in c.calls.list())
    assert set(table.index) == storage_keys
