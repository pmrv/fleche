"""Regression tests for issue #319: query().table() index must match actual storage keys.

The DataFrame returned by cache.table() or query().table() uses LazyCall.to_lookup_key()
as row labels. These must equal the keys in calls.list() so that users can load calls by
index, and so that cache.contains() / cache.load() are consistent with the table view.
"""
import pytest

from fleche import fleche, cache, tags
from fleche.call import Call, QueryCall
from fleche.caches import Cache
from fleche.storage.memory import ValueMemory, CallMemory
from fleche.storage.sql import Sql


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _storage_keys(c: Cache) -> set[str]:
    return {str(k) for k in c.calls.list()}


def _table_keys(c: Cache) -> set[str]:
    return set(c.table().index.tolist())


# ---------------------------------------------------------------------------
# Memory backend
# ---------------------------------------------------------------------------

def test_table_index_equals_storage_keys_memory():
    """table().index must exactly equal calls.list() for a memory-backed cache."""
    c = Cache(values=ValueMemory({}), calls=CallMemory({}))
    c.save(Call(name="f", arguments={"x": 1}, result=10))
    c.save(Call(name="f", arguments={"x": 2}, result=20))
    c.save(Call(name="g", arguments={"a": "hello", "b": 3.14}, result=None))

    assert _table_keys(c) == _storage_keys(c)


def test_table_index_loadable_memory():
    """Every key in table().index must be loadable via cache.load() without error."""
    c = Cache(values=ValueMemory({}), calls=CallMemory({}))
    c.save(Call(name="f", arguments={"x": 1}, result=10))
    c.save(Call(name="f", arguments={"x": 2}, result=20))

    for key in _table_keys(c):
        lc = c.load(key, lazy=True)
        assert lc.name == "f"


# ---------------------------------------------------------------------------
# SQL backend
# ---------------------------------------------------------------------------

def test_table_index_equals_storage_keys_sql(tmp_path):
    """table().index must exactly equal calls.list() for a SQL-backed cache."""
    c = Cache(values=ValueMemory({}), calls=Sql(str(tmp_path / "test.db")))
    c.save(Call(name="f", arguments={"x": 1}, result=10))
    c.save(Call(name="f", arguments={"x": 2}, result=20))
    c.save(Call(name="g", arguments={"a": "hello", "b": 3.14}, result=None))

    assert _table_keys(c) == _storage_keys(c)


def test_table_index_loadable_sql(tmp_path):
    """Every key in table().index must be loadable via cache.load() for SQL backend."""
    c = Cache(values=ValueMemory({}), calls=Sql(str(tmp_path / "test.db")))
    c.save(Call(name="f", arguments={"x": 1}, result=10))
    c.save(Call(name="f", arguments={"x": 2}, result=20))

    for key in _table_keys(c):
        lc = c.load(key, lazy=True)
        assert lc.name == "f"


# ---------------------------------------------------------------------------
# @fleche decorator — adds module and code_digest to key
# ---------------------------------------------------------------------------

def test_table_index_equals_storage_keys_fleche_decorator():
    """table().index must match calls.list() when calls come from the @fleche decorator."""
    c = Cache(values=ValueMemory({}), calls=CallMemory({}))
    with cache(c):
        @fleche
        def add(x, y):
            return x + y

        add(1, 2)
        add(3, 4)
        add(5, 6)

    assert _table_keys(c) == _storage_keys(c)


def test_table_index_loadable_fleche_decorator():
    """Keys from table().index must load successfully when produced by @fleche."""
    c = Cache(values=ValueMemory({}), calls=CallMemory({}))
    with cache(c):
        @fleche
        def square(n):
            return n * n

        square(3)
        square(7)

        for key in _table_keys(c):
            lc = c.load(key, lazy=True)
            assert lc.name == "square"


# ---------------------------------------------------------------------------
# @fleche decorator + metadata (tags) — metadata excluded from key
# ---------------------------------------------------------------------------

def test_table_index_equals_storage_keys_with_tags():
    """Metadata (tags) must not corrupt the table index vs storage keys."""
    c = Cache(values=ValueMemory({}), calls=CallMemory({}))
    with cache(c):
        @fleche
        def compute(x):
            return x * 2

        with tags(run="A", iteration=1):
            compute(10)
        with tags(run="B", iteration=2):
            compute(20)
        compute(30)

    assert _table_keys(c) == _storage_keys(c)


def test_table_index_equals_storage_keys_sql_with_tags(tmp_path):
    """Metadata tags must not corrupt the SQL-backed table index vs storage keys."""
    c = Cache(values=ValueMemory({}), calls=Sql(str(tmp_path / "test.db")))
    with cache(c):
        @fleche
        def compute(x):
            return x * 2

        with tags(t1="v1", t2="v2"):
            compute(1)
        compute(2)

    assert _table_keys(c) == _storage_keys(c)


# ---------------------------------------------------------------------------
# Multi-argument functions — argument order must be preserved in the key
# ---------------------------------------------------------------------------

def test_table_index_equals_storage_keys_multi_arg():
    """Keys must be stable regardless of the number of arguments."""
    c = Cache(values=ValueMemory({}), calls=CallMemory({}))
    c.save(Call(name="f", arguments={"a": 1, "b": 2, "c": 3}, result=6))
    c.save(Call(name="f", arguments={"a": 4, "b": 5, "c": 6}, result=15))
    c.save(Call(name="f", arguments={"a": 0, "b": 0, "c": 0}, result=0))

    assert _table_keys(c) == _storage_keys(c)


# ---------------------------------------------------------------------------
# Wrapper digest() matches table().index
# ---------------------------------------------------------------------------

def test_wrapper_digest_appears_in_table_index():
    """f.digest(*args) must appear as an index entry in f.query().table()."""
    c = Cache(values=ValueMemory({}), calls=CallMemory({}))
    with cache(c):
        @fleche
        def mul(x, y):
            return x * y

        mul(2, 3)
        mul(4, 5)

        table = mul.query().table()
        assert str(mul.digest(2, 3)) in set(table.index)
        assert str(mul.digest(4, 5)) in set(table.index)


def test_wrapper_digest_matches_cache_load_key():
    """f.digest(*args) must also work directly with cache.load() — same key as table index."""
    c = Cache(values=ValueMemory({}), calls=CallMemory({}))
    with cache(c):
        @fleche
        def power(base, exp):
            return base ** exp

        power(2, 8)
        power(3, 3)

        for base, exp in [(2, 8), (3, 3)]:
            key = str(power.digest(base, exp))
            lc = c.load(key, lazy=True)
            assert lc.name == "power"


# ---------------------------------------------------------------------------
# Versioned wrapper — version included in key
# ---------------------------------------------------------------------------

def test_table_index_equals_storage_keys_versioned():
    """Version field must be consistently included in key for both storage and table."""
    c = Cache(values=ValueMemory({}), calls=CallMemory({}))
    with cache(c):
        @fleche(version=1)
        def versioned(x):
            return x

        versioned(1)
        versioned(2)

    assert _table_keys(c) == _storage_keys(c)


# ---------------------------------------------------------------------------
# Empty cache
# ---------------------------------------------------------------------------

def test_table_index_empty_cache():
    """Empty cache must produce an empty table with no index entries."""
    c = Cache(values=ValueMemory({}), calls=CallMemory({}))
    assert _table_keys(c) == _storage_keys(c) == set()


# ---------------------------------------------------------------------------
# Eviction: after evicting a key, table index must still match storage
# ---------------------------------------------------------------------------

def test_table_index_after_eviction():
    """After evicting a call, table index must still equal remaining storage keys."""
    c = Cache(values=ValueMemory({}), calls=CallMemory({}))
    c.save(Call(name="f", arguments={"x": 1}, result=10))
    c.save(Call(name="f", arguments={"x": 2}, result=20))
    c.save(Call(name="f", arguments={"x": 3}, result=30))

    keys_before = list(_storage_keys(c))
    c.evict(keys_before[0])

    assert _table_keys(c) == _storage_keys(c)
    assert len(_table_keys(c)) == 2
