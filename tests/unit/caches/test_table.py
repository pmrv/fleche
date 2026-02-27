from fleche.storage import Memory
from fleche.caches import Cache
from fleche.call import Call
import pandas as pd
import pytest

def test_cache_table_populated():
    values = Memory({})
    calls = Memory({})
    cache = Cache(values, calls)

    # Add some calls
    c1 = Call(
        name="func_1",
        arguments={"a": 1},
        result=1,
        metadata={"meta": {"tag": "tag_1", "extra": 2}},
        module="mod",
        version="1.0"
    )
    cache.save(c1)

    c2 = Call(
        name="func_2",
        arguments={"a": 2},
        result=2,
        metadata={"other": {"flag": True}},
        module="mod",
        version="1.0"
    )
    cache.save(c2)

    df = cache.table()

    assert isinstance(df, pd.DataFrame)
    assert len(df) == 2
    # Check index
    assert c1.to_lookup_key() in df.index
    assert c2.to_lookup_key() in df.index

    # Check columns - flattened metadata
    assert "tag" in df.columns
    assert "extra" in df.columns
    assert "flag" in df.columns
    assert "name" in df.columns
    assert "module" in df.columns

    # Check values
    row1 = df.loc[c1.to_lookup_key()]
    assert row1["name"] == "func_1"
    assert row1["tag"] == "tag_1"

    row2 = df.loc[c2.to_lookup_key()]
    assert row2["name"] == "func_2"
    assert row2["flag"] == True

def test_cache_table_empty():
    values = Memory({})
    calls = Memory({})
    cache = Cache(values, calls)

    df = cache.table()

    assert isinstance(df, pd.DataFrame)
    assert df.empty
