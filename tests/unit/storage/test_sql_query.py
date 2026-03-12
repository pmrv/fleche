import pytest
from pathlib import Path

from fleche.storage.sql import Sql
from fleche.call import Call
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
    k1 = store.save(c1)
    k2 = store.save(c2)
    k3 = store.save(c3)

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
    k1 = store.save(c1)
    k2 = store.save(c2)
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
    k1 = store.save(c1)
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
    k1 = store.save(c1)
    k2 = store.save(c2)
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
    k1 = store.save(c1)
    k2 = store.save(c2)
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
    k1 = store.save(c1)
    k2 = store.save(c2)
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
    k1 = store.save(c1)
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
        code_digest="some_code_digest",
        result=digest(3)
    )

    key = store.save(original)
    loaded = store.load(key)

    assert loaded.code_digest == "some_code_digest"
    assert loaded.to_lookup_key() == original.to_lookup_key()
    assert loaded == original
