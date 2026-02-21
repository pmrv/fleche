
import pytest
from fleche.storage.sql import Sql
from fleche.call import Call, Statistics

def test_sql_stats_persistence(tmp_path):
    db_path = tmp_path / "stats.db"
    store = Sql(str(db_path))

    call = Call(
        name="test_stats",
        arguments={"x": "x" * 64},
        stats=Statistics(hits=42, misses=7)
    )

    key = store.save(call)

    # Reload from fresh store instance to be sure it's in DB
    store2 = Sql(str(db_path))
    loaded = store2.load(key)

    assert loaded.stats.hits == 42
    assert loaded.stats.misses == 7

def test_sql_stats_update(tmp_path):
    db_path = tmp_path / "stats_update.db"
    store = Sql(str(db_path))

    call = Call(name="test", arguments={})
    key = store.save(call)

    loaded = store.load(key)
    assert loaded.stats.hits == 0
    assert loaded.stats.misses == 0

    # Update stats
    loaded.stats.hits = 10
    loaded.stats.misses = 5
    store.save(loaded, key=key)

    loaded2 = store.load(key)
    assert loaded2.stats.hits == 10
    assert loaded2.stats.misses == 5
