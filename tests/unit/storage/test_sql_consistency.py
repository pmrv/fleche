import pytest
import random
from fleche.call import Call
from fleche.caches import Cache
from fleche.storage import Memory, Sql
from fleche.digest import digest

def test_sql_query_matches_call_matches():
    """Verify that Sql storage query results are consistent with Call.matches()."""
    # Use Memory as a baseline value storage for both
    values = Memory({})
    sql_calls = Sql() # in-memory sqlite
    cache = Cache(values, sql_calls)

    # Populate cache with varied calls
    names = ["foo", "bar", "baz"]
    modules = ["mod1", "mod2", None]
    versions = [1, 2, None]

    for i in range(20):
        c = Call(
            name=random.choice(names),
            arguments={"x": random.randint(0, 5), "y": random.choice(["a", "b"])},
            metadata={"tags": {"id": i, "even": i % 2 == 0}},
            module=random.choice(modules),
            version=random.choice(versions),
            result=random.randint(100, 200)
        )
        cache.save(c)

    # Test various templates
    templates = [
        Call(name="foo", arguments=None),
        Call(name=None, arguments={"x": 1}),
        Call(name="bar", arguments={"y": "a"}),
        Call(name=None, arguments=None, metadata={"tags": {"even": True}}),
        Call(name="baz", module="mod1", version=1, arguments=None),
        Call(name=None, result=None, arguments=None) # match all
    ]

    for template in templates:
        for c in cache.query(template):
            assert template.matches(c)
