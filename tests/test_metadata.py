
import time

import pytest

from fleche import fleche, cache, tags, project, metadata
from fleche.cache import Cache
from fleche.metadata import MetaData, PandasDB, Invocation
from fleche.storage import MemoryStorage


@pytest.fixture
def cache_it() -> Cache:
    db = PandasDB({})
    storage = MemoryStorage({})
    return Cache(db, storage)


def test_fleche_decorator_default_metadata(cache_it: Cache):
    @fleche
    def my_function(a: int, b: int) -> int:
        return a + b

    with cache(cache_it):
        my_function(1, 2)
        time.sleep(0.1)
        my_function(1, 2)

    df = cache_it.metadata.table()
    assert "walltime" in df.columns
    assert "result" in df.columns
    assert len(df) == 1
    assert df['walltime'].iloc[0] < 0.1


def test_fleche_decorator_custom_metadata(cache_it: Cache):
    class MyMetadata(MetaData):
        name = "my_meta"
        keys = {"my_key": str}

        def pre(self, invocation: Invocation):
            return {"my_key": "my_value"}

    @fleche(meta=(MyMetadata(),))
    def my_function(a: int, b: int) -> int:
        return a + b

    with cache(cache_it):
        my_function(1, 2)

    df = cache_it.metadata.table()
    assert "my_key" in df.columns
    assert df["my_key"].iloc[0] == "my_value"


def test_metadata_context_manager(cache_it: Cache):
    class MyMetadata(MetaData):
        name = "my_meta"
        keys = {"my_key": str}

        def pre(self, invocation: Invocation):
            return {"my_key": "my_value"}

    @fleche
    def my_function(a: int, b: int) -> int:
        return a + b

    with cache(cache_it):
        with metadata(MyMetadata()):
            my_function(1, 2)

    df = cache_it.metadata.table()
    assert "my_key" in df.columns
    assert df["my_key"].iloc[0] == "my_value"


def test_metadata_context_manager_stacking(cache_it: Cache):
    class MyMetadata1(MetaData):
        name = "my_meta1"
        keys = {"my_key1": str}

        def pre(self, invocation: Invocation):
            return {"my_key1": "my_value1"}

    class MyMetadata2(MetaData):
        name = "my_meta2"
        keys = {"my_key2": str}

        def pre(self, invocation: Invocation):
            return {"my_key2": "my_value2"}

    @fleche
    def my_function(a: int, b: int) -> int:
        return a + b

    with cache(cache_it):
        with metadata(MyMetadata1()):
            with metadata(MyMetadata2(), stack=True):
                my_function(1, 2)

    df = cache_it.metadata.table()
    assert "my_key1" in df.columns
    assert "my_key2" in df.columns
    assert df["my_key1"].iloc[0] == "my_value1"
    assert df["my_key2"].iloc[0] == "my_value2"


def test_metadb_table_filtering(cache_it: Cache):
    class MyMetadata(MetaData):
        name = "my_meta"
        keys = {"my_key": str, "my_other_key": int}

        def pre(self, invocation: Invocation):
            if invocation.kwargs.get("b") == 2:
                return {"my_key": "my_value", "my_other_key": 1}
            return {"my_key": "another_value", "my_other_key": 2}

    @fleche(meta=(MyMetadata(),))
    def my_function(a: int, b: int) -> int:
        return a + b

    with cache(cache_it):
        my_function(a=1, b=2)
        my_function(a=2, b=3)

    df = cache_it.metadata.table()
    assert len(df) == 2

    df_filtered = cache_it.metadata.table(my_key="my_value")
    assert len(df_filtered) == 1

    df_filtered = cache_it.metadata.table(my_other_key=2)
    assert len(df_filtered) == 1

    df_filtered = cache_it.metadata.table(my_other_key=3)
    assert len(df_filtered) == 0

    df_filtered = cache_it.metadata.table(my_key="my_value", my_other_key=1)
    assert len(df_filtered) == 1

    df_filtered = cache_it.metadata.table(my_key="my_value", my_other_key=2)
    assert len(df_filtered) == 0


def test_fleche_decorator_and_context_manager(cache_it: Cache):
    class MyMetadata1(MetaData):
        name = "my_meta1"
        keys = {"my_key1": str}

        def pre(self, invocation: Invocation):
            return {"my_key1": "my_value1"}

    class MyMetadata2(MetaData):
        name = "my_meta2"
        keys = {"my_key2": str}

        def pre(self, invocation: Invocation):
            return {"my_key2": "my_value2"}

    @fleche(meta=(MyMetadata1(),))
    def my_function(a: int, b: int) -> int:
        return a + b

    with cache(cache_it):
        with metadata(MyMetadata2()):
            my_function(1, 2)

    df = cache_it.metadata.table()
    assert "my_key1" in df.columns
    assert "my_key2" in df.columns
    assert df["my_key1"].iloc[0] == "my_value1"
    assert df["my_key2"].iloc[0] == "my_value2"


def test_tags():
    storage = MemoryStorage({})
    mdb = PandasDB({})

    with cache(Cache(mdb, storage)):

        @fleche
        def my_func(a, b):
            return a + b

        with tags(user="test", project="fleche"):
            my_func(1, 2)

        df = mdb.table()
        assert "user" in df.columns
        assert "project" in df.columns
        assert df.iloc[0]["user"] == "test"
        assert df.iloc[0]["project"] == "fleche"

        with project("example"):
            my_func(2, 1)

        df = mdb.table()
        assert df.iloc[1]["project"] == "example"
