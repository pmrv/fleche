import pytest

from hypothesis import given, strategies as st

from fleche.storage.sql import Sql
from fleche.storage import ValueMemory
from fleche.caches import Cache
from fleche.call import Call, QueryCall
from fleche.digest import Digest, digest


def make_calls():
    c1 = Call(
        name="f1",
        arguments={"a": "a" * 64, "b": "b" * 64},
        metadata={},
        module="m",
        version=1,
        result="r" * 64,
    )
    c2 = Call(
        name="f1",
        arguments={"a": "a" * 64, "b": "x" * 64},
        metadata={},
        module="m",
        version=2,
        result="s" * 64,
    )
    c3 = Call(
        name="f2",
        arguments={"c": "c" * 64},
        metadata={},
        module=None,
        version=None,
        result=None,
    )
    return c1, c2, c3


def keys(calls):
    return {c.to_lookup_key() for c in calls}


def slow_query_keys(store: Sql, tpl: Call):
    # Reproduce generic CallStorage.query semantics for baseline comparison
    def none_or_equal(a, b):
        return a is None or digest(a) == digest(b)

    def fits(call: Call) -> bool:
        try:
            return (
                none_or_equal(tpl.name, call.name)
                and none_or_equal(tpl.module, call.module)
                and none_or_equal(tpl.version, call.version)
                and none_or_equal(tpl.result, call.result)
                and (
                    tpl.arguments is None
                    or all(
                        none_or_equal(v, call.arguments[k])
                        for k, v in tpl.arguments.items()
                    )
                )
            )
        except KeyError:
            return False

    matched = []
    for k in store.list():
        call = store.load(k)
        if fits(call):
            matched.append(call)
    return keys(matched)


@pytest.fixture()
def store(tmp_path):
    return Sql(str(tmp_path / "calls.db"))


def test_sql_query_all_returns_all(store):
    """Query with fully-wildcard template should return all saved calls.

    Invariant: The SQL-backed query must match the generic baseline selection
    when no fields are constrained (all None), i.e., the set of keys is equal.
    """
    c1, c2, c3 = make_calls()
    store.save(c1)
    store.save(c2)
    store.save(c3)

    tpl = Call(
        name=None, arguments=None, metadata=None, module=None, version=None, result=None
    )
    got = list(store.query(tpl))
    assert keys(got) == slow_query_keys(
        store, tpl
    ), "Wildcard query should return all calls; SQL and baseline sets must match"


def test_sql_query_by_name(store):
    """Query constrained by name should return only calls with that name.

    Invariant: SQL-backed query returns the same key set as the baseline when
    filtering by name alone.
    """
    c1, c2, c3 = make_calls()
    store.save(c1)
    store.save(c2)
    store.save(c3)

    tpl = Call(
        name="f1", arguments=None, metadata=None, module=None, version=None, result=None
    )
    got = list(store.query(tpl))
    assert keys(got) == slow_query_keys(
        store, tpl
    ), "Filtering by name must match baseline-selected keys"


def test_sql_query_by_name_and_version(store):
    """Query constrained by name and version should match exactly one call.

    Invariant: SQL-backed query equals baseline for combined scalar filters.
    """
    c1, c2, c3 = make_calls()
    store.save(c1)
    store.save(c2)
    store.save(c3)

    tpl = Call(
        name="f1", arguments=None, metadata=None, module=None, version=1, result=None
    )
    got = list(store.query(tpl))
    assert keys(got) == slow_query_keys(
        store, tpl
    ), "Filtering by name+version must match baseline-selected keys"


def test_sql_query_by_argument_digest_string(store):
    """Argument filter using a digest string should match both calls with that arg.

    Invariant: SQL normalizes digest(template_val) for comparison and must match
    the baseline selection using digest semantics.
    """
    c1, c2, c3 = make_calls()
    store.save(c1)
    store.save(c2)
    store.save(c3)

    # Filter by a single argument using its digest string value
    tpl = Call(
        name=None,
        arguments={"a": "a" * 64},
        metadata=None,
        module=None,
        version=None,
        result=None,
    )
    got = list(store.query(tpl))
    assert keys(got) == slow_query_keys(
        store, tpl
    ), "Argument filter by digest string must match baseline-selected keys"


def test_sql_query_by_argument_digest_object(store):
    """Argument filter using a Digest object should match expected subset.

    Invariant: SQL digest normalization must make Digest objects equivalent to
    strings for filtering, matching the baseline.
    """
    c1, c2, c3 = make_calls()
    store.save(c1)
    store.save(c2)
    store.save(c3)

    # Same filter but with Digest object
    tpl = Call(
        name=None,
        arguments={"b": Digest("b" * 64)},
        metadata=None,
        module=None,
        version=None,
        result=None,
    )
    got = list(store.query(tpl))
    assert keys(got) == slow_query_keys(
        store, tpl
    ), "Argument filter by Digest object must match baseline-selected keys"


def test_sql_query_argument_wildcard_none(store):
    """None as an argument value means 'key present' wildcard match.

    Invariant: For a given arg key, None should match any value when the key
    exists, and should not match when the key is absent. SQL query must equal
    baseline.
    """
    c1, c2, c3 = make_calls()
    store.save(c1)
    store.save(c2)
    store.save(c3)

    # None in arguments acts as wildcard but requires presence of the key
    tpl = Call(
        name="f1",
        arguments={"b": None},
        metadata=None,
        module=None,
        version=None,
        result=None,
    )
    got = list(store.query(tpl))
    assert keys(got) == slow_query_keys(
        store, tpl
    ), "Wildcard None for existing arg key must match baseline"

    # Key not present shouldn't match
    tpl2 = Call(
        name=None,
        arguments={"not_there": None},
        metadata=None,
        module=None,
        version=None,
        result=None,
    )
    got2 = list(store.query(tpl2))
    assert keys(got2) == slow_query_keys(
        store, tpl2
    ), "Wildcard None for a missing arg key must match empty baseline selection"


def test_sql_query_by_result(store):
    """Result filter should use digest semantics and match the correct call(s).

    Invariant: SQL-backed result filtering equals baseline selection by digest.
    """
    c1, c2, c3 = make_calls()
    store.save(c1)
    store.save(c2)
    store.save(c3)

    tpl = Call(
        name=None,
        arguments=None,
        metadata=None,
        module=None,
        version=None,
        result=Digest("r" * 64),
    )
    got = list(store.query(tpl))
    assert keys(got) == slow_query_keys(
        store, tpl
    ), "Result filter must match baseline-selected keys by digest"


def test_sql_call_digest_persistence(store):
    """A call saved to SQL must retain the same digest before and after loading.

    Regression test: ensures code_digest and other key-relevant fields are
    persisted and correctly re-loaded so that to_lookup_key() remains stable.
    """
    original = Call(
        name="test_func",
        arguments={"a": digest(1)},
        metadata={"m": {"k": "v"}},
        module="mod",
        version=42,
        code_digest=Digest("some_code_digest"),
        result=digest(3)
    )

    key = store.save(original)
    loaded = store.load(key)

    assert loaded.code_digest == "some_code_digest"
    assert loaded.to_lookup_key() == original.to_lookup_key()
    assert loaded == original


# ---------------------------------------------------------------------------
# Version type round-trips (str | int | None all preserved through SQL)
# ---------------------------------------------------------------------------


def test_sql_string_version_roundtrip(store):
    """String version is stored and loaded with its type preserved."""
    c = Call(
        name="f",
        arguments={"x": Digest("a" * 64)},
        metadata={},
        module="mod",
        version="1.2.3",
        result=Digest("r" * 64),
    )
    key = store.save(c)
    loaded = store.load(key)
    assert loaded.version == "1.2.3"
    assert isinstance(loaded.version, str)
    assert loaded.to_lookup_key() == c.to_lookup_key()


def test_sql_int_version_roundtrip(store):
    """Integer version is stored and loaded with its type preserved."""
    c = Call(
        name="f",
        arguments={"x": Digest("a" * 64)},
        metadata={},
        module="mod",
        version=42,
        result=Digest("r" * 64),
    )
    key = store.save(c)
    loaded = store.load(key)
    assert loaded.version == 42
    assert isinstance(loaded.version, int)
    assert loaded.to_lookup_key() == c.to_lookup_key()


def test_sql_query_by_string_version(store):
    """Querying by string version returns only calls with that exact version."""
    c1 = Call(
        name="f",
        arguments={"x": Digest("a" * 64)},
        metadata={},
        module="mod",
        version="1.0.0",
        result=Digest("r" * 64),
    )
    c2 = Call(
        name="f",
        arguments={"x": Digest("b" * 64)},
        metadata={},
        module="mod",
        version="2.0.0",
        result=Digest("s" * 64),
    )
    store.save(c1)
    store.save(c2)

    tpl = Call(name=None, arguments=None, metadata=None, module=None, version="1.0.0", result=None)
    got = list(store.query(tpl))
    assert len(got) == 1
    assert got[0].version == "1.0.0"


# ---------------------------------------------------------------------------
# Consistency: SQL query vs QueryCall.matches()
# ---------------------------------------------------------------------------


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
    """Verify that Sql storage query results are consistent with QueryCall.matches()."""
    values = ValueMemory({})
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

    template = QueryCall(
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


# ---------------------------------------------------------------------------
# Metadata query filters
# ---------------------------------------------------------------------------


def make_metadata_calls():
    c1 = Call(
        name="f1",
        arguments={"a": "a" * 64},
        metadata={
            "runtime": {"walltime": 1.23, "timestart": 0.1, "timestop": 1.33},
            "tags": {"project": "alpha", "phase": "train"},
            "flags": {"ok": True, "count": 3},
            "complex": {"listy": [1, 2]},
        },
        module=None,
        version=None,
        result=None,
    )

    c2 = Call(
        name="f2",
        arguments={"b": "b" * 64},
        metadata={
            "runtime": {"walltime": 2.0},
            "tags": {"project": "beta", "phase": "eval"},
            "flags": {"ok": False, "count": 7},
            "complex": {"listy": [1, 3]},
        },
        module=None,
        version=None,
        result=None,
    )

    return c1, c2


def test_find_by_metadata_name_only_returns_all_with_that_name(store):
    """Empty dict for a metadata name means 'presence of that name'.

    Intent: When metadata={"tags": {}}, query should return any call that has
    a 'tags' metadata entry, regardless of its keys/values.
    """
    c1, c2 = make_metadata_calls()
    store.save(c1)
    store.save(c2)

    # Name only: return all keys that have this metadata name
    # Name-only selection using query(): require presence of at least one key from that name
    tpl = Call(
        name=None,
        arguments=None,
        metadata={"tags": {}},
        module=None,
        version=None,
        result=None,
    )
    names = {c.name for c in store.query(tpl)}
    assert names == {
        "f1",
        "f2",
    }, "Presence-only metadata filter should include both calls with 'tags'"


def test_find_by_metadata_multiple_filters(store):
    """Multiple key filters within a single metadata name are AND-combined.

    Intent: metadata={"tags": {"project": "alpha", "phase": "train"}} should
    match only the call whose 'tags' has both project=alpha and phase=train.
    """
    c1, c2 = make_metadata_calls()
    store.save(c1)
    store.save(c2)

    # Multiple key filters within same metadata name
    tpl = Call(
        name=None,
        arguments=None,
        metadata={"tags": {"project": "alpha", "phase": "train"}},
        module=None,
        version=None,
        result=None,
    )
    names = {c.name for c in store.query(tpl)}
    assert names == {
        "f1"
    }, "Both project=alpha and phase=train must be satisfied simultaneously"


def test_find_by_metadata_boolean_and_integer_filters(store):
    """Boolean and integer filters should match correctly server-side.

    Intent: metadata simple types (bool/int) should be pushed down to SQL JSON
    expressions and yield precise matches.
    """
    c1, c2 = make_metadata_calls()
    store.save(c1)
    store.save(c2)

    # Boolean filter
    tpl1 = Call(
        name=None,
        arguments=None,
        metadata={"flags": {"ok": True}},
        module=None,
        version=None,
        result=None,
    )
    ok_true = {c.name for c in store.query(tpl1)}
    assert ok_true == {"f1"}, "flags.ok == True should select only f1"

    # Integer filter
    tpl2 = Call(
        name=None,
        arguments=None,
        metadata={"flags": {"count": 3}},
        module=None,
        version=None,
        result=None,
    )
    count_three = {c.name for c in store.query(tpl2)}
    assert count_three == {"f1"}, "flags.count == 3 should select only f1"


def test_find_by_metadata_across_all_names(store):
    """Filtering within a specific metadata name works; name can vary per test.

    Intent: Using metadata={"runtime": {"walltime": 2.0}} should find the call
    where runtime.walltime equals 2.0.
    """
    c1, c2 = make_metadata_calls()
    store.save(c1)
    store.save(c2)

    # Without name, search across all metadata names (e.g., walltime under runtime)
    tpl = Call(
        name=None,
        arguments=None,
        metadata={"runtime": {"walltime": 2.0}},
        module=None,
        version=None,
        result=None,
    )
    names = {c.name for c in store.query(tpl)}
    assert names == {"f2"}, "runtime.walltime == 2.0 should select only f2"


def test_find_by_metadata_fallback_for_unsupported_types(store):
    """Unsupported types (e.g., list) use client-side fallback but must match.

    Intent: metadata={"complex": {"listy": [1, 2]}} selects f1 even though the
    list forces client-side validation.
    """
    c1, c2 = make_metadata_calls()
    store.save(c1)
    store.save(c2)

    # Lists are not in the supported (str, bool, int, float); this should use the
    # client-side fallback path but still return a correct set.
    tpl = Call(
        name=None,
        arguments=None,
        metadata={"complex": {"listy": [1, 2]}},
        module=None,
        version=None,
        result=None,
    )
    names = {c.name for c in store.query(tpl)}
    assert names == {
        "f1"
    }, "List-valued filter should be handled client-side and still match f1"


def test_find_by_metadata_no_matches_returns_empty(store):
    """Non-existent metadata value yields an empty result set.

    Intent: metadata={"tags": {"project": "gamma"}} should not match either
    call since no 'project' has value 'gamma'.
    """
    c1, c2 = make_metadata_calls()
    store.save(c1)
    store.save(c2)

    tpl = Call(
        name=None,
        arguments=None,
        metadata={"tags": {"project": "gamma"}},
        module=None,
        version=None,
        result=None,
    )
    names = {c.name for c in store.query(tpl)}
    assert (
        names == set()
    ), "No call has tags.project == 'gamma'; result set must be empty"
