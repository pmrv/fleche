import pytest
from hypothesis import given, strategies as st
from fleche.call import Call
from fleche.caches import Cache
from fleche.storage import Memory, Sql


@given(
    st.lists(
        st.fixed_dictionaries(
            {
                "name": st.sampled_from(["foo", "bar", "baz"]),
                "module": st.one_of(st.none(), st.sampled_from(["mod1", "mod2"])),
                "version": st.one_of(st.none(), st.integers(1, 2)),
                "result": st.integers(100, 110),
                "x": st.integers(0, 5),
                "y": st.sampled_from(["a", "b"]),
            }
        ),
        min_size=5,
        max_size=10,
        unique_by=lambda d: (d["name"], d["module"], d["version"], d["x"], d["y"]),
    ),
    st.fixed_dictionaries(
        {
            "name": st.one_of(st.none(), st.sampled_from(["foo", "bar", "baz"])),
            "module": st.one_of(st.none(), st.sampled_from(["mod1", "mod2"])),
            "version": st.one_of(st.none(), st.integers(1, 2)),
            "result": st.one_of(st.none(), st.integers(100, 110)),
            "x": st.one_of(st.none(), st.integers(0, 5)),
            "y": st.one_of(st.none(), st.sampled_from(["a", "b"])),
        }
    ),
)
def test_sql_query_matches_call_matches(call_data, template_data):
    """Verify that Sql storage query results are consistent with Call.matches()."""
    values = Memory({})
    sql_calls = Sql()  # in-memory sqlite
    cache = Cache(values, sql_calls)

    # Populate cache and pre-calculate lookup keys
    calls_with_keys = []
    for d in call_data:
        c = Call(
            name=d["name"],
            arguments={"x": d["x"], "y": d["y"]},
            module=d["module"],
            version=d["version"],
            result=d["result"],
        )
        cache.save(c)
        calls_with_keys.append((c, c.to_lookup_key()))

    # Build template
    template_args = {}
    if template_data["x"] is not None:
        template_args["x"] = template_data["x"]
    if template_data["y"] is not None:
        template_args["y"] = template_data["y"]

    template = Call(
        name=template_data["name"],
        arguments=template_args if template_args else None,
        module=template_data["module"],
        version=template_data["version"],
        result=template_data["result"],
    )

    # Check consistency
    query_keys = {c.to_lookup_key() for c in cache.query(template)}
    for c in cache.query(template):
        assert template.matches(c)

    # Verify we didn't miss any
    expected_keys = {key for c, key in calls_with_keys if template.matches(c)}
    assert query_keys == expected_keys
