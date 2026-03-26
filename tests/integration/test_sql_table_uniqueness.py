
import pytest
from fleche import fleche, cache, tags

def test_sql_table_uniqueness(cache_fixture):
    """Integration test to verify that cache.table() does not contain more items than cache.calls.list()
    when using a SQL backend, even with joins.
    """
    c = cache_fixture

    with cache(c):
        @fleche
        def my_func(a, b):
            return a + b

        # Use multiple tags to ensure multiple rows in metadata table if not distinct
        with tags(t1="v1", t2="v2"):
            my_func(1, 2)

        # Use multiple arguments to ensure multiple rows in arguments table if not distinct
        my_func(a=3, b=4)

        # Check counts
        num_calls = len(list(c.calls.list()))
        table_df = c.table()

        assert len(table_df) == num_calls, "Table should have exactly one row per call"
        assert table_df.index.is_unique, "Table index must be unique"
