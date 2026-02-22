import pytest

from fleche.storage.sql import Sql
from fleche.call import Call


def make_calls():
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


@pytest.fixture()
def store(tmp_path):
    return Sql(str(tmp_path / "calls.db"))


def test_find_by_metadata_name_only_returns_all_with_that_name(store):
    """Empty dict for a metadata name means 'presence of that name'.

    Intent: When metadata={"tags": {}}, query should return any call that has
    a 'tags' metadata entry, regardless of its keys/values.
    """
    c1, c2 = make_calls()
    k1 = store.save(c1)
    k2 = store.save(c2)

    # Name only: return all keys that have this metadata name
    # Name-only selection using query(): require presence of at least one key from that name
    tpl = Call(name=None, arguments=None, metadata={"tags": {}}, module=None, version=None, result=None)
    names = {c.name for c in store.query(tpl)}
    assert names == {"f1", "f2"}, (
        "Presence-only metadata filter should include both calls with 'tags'"
    )


def test_find_by_metadata_multiple_filters(store):
    """Multiple key filters within a single metadata name are AND-combined.

    Intent: metadata={"tags": {"project": "alpha", "phase": "train"}} should
    match only the call whose 'tags' has both project=alpha and phase=train.
    """
    c1, c2 = make_calls()
    k1 = store.save(c1)
    store.save(c2)

    # Multiple key filters within same metadata name
    tpl = Call(name=None, arguments=None, metadata={"tags": {"project": "alpha", "phase": "train"}}, module=None, version=None, result=None)
    names = {c.name for c in store.query(tpl)}
    assert names == {"f1"}, (
        "Both project=alpha and phase=train must be satisfied simultaneously"
    )


def test_find_by_metadata_boolean_and_integer_filters(store):
    """Boolean and integer filters should match correctly server-side.

    Intent: metadata simple types (bool/int) should be pushed down to SQL JSON
    expressions and yield precise matches.
    """
    c1, c2 = make_calls()
    k1 = store.save(c1)
    store.save(c2)

    # Boolean filter
    tpl1 = Call(name=None, arguments=None, metadata={"flags": {"ok": True}}, module=None, version=None, result=None)
    ok_true = {c.name for c in store.query(tpl1)}
    assert ok_true == {"f1"}, (
        "flags.ok == True should select only f1"
    )

    # Integer filter
    tpl2 = Call(name=None, arguments=None, metadata={"flags": {"count": 3}}, module=None, version=None, result=None)
    count_three = {c.name for c in store.query(tpl2)}
    assert count_three == {"f1"}, (
        "flags.count == 3 should select only f1"
    )


def test_find_by_metadata_across_all_names(store):
    """Filtering within a specific metadata name works; name can vary per test.

    Intent: Using metadata={"runtime": {"walltime": 2.0}} should find the call
    where runtime.walltime equals 2.0.
    """
    c1, c2 = make_calls()
    store.save(c1)
    k2 = store.save(c2)

    # Without name, search across all metadata names (e.g., walltime under runtime)
    tpl = Call(name=None, arguments=None, metadata={"runtime": {"walltime": 2.0}}, module=None, version=None, result=None)
    names = {c.name for c in store.query(tpl)}
    assert names == {"f2"}, (
        "runtime.walltime == 2.0 should select only f2"
    )


def test_find_by_metadata_fallback_for_unsupported_types(store):
    """Unsupported types (e.g., list) use client-side fallback but must match.

    Intent: metadata={"complex": {"listy": [1, 2]}} selects f1 even though the
    list forces client-side validation.
    """
    c1, c2 = make_calls()
    k1 = store.save(c1)
    store.save(c2)

    # Lists are not in the supported (str, bool, int, float); this should use the
    # client-side fallback path but still return a correct set.
    tpl = Call(name=None, arguments=None, metadata={"complex": {"listy": [1, 2]}}, module=None, version=None, result=None)
    names = {c.name for c in store.query(tpl)}
    assert names == {"f1"}, (
        "List-valued filter should be handled client-side and still match f1"
    )


def test_find_by_metadata_no_matches_returns_empty(store):
    """Non-existent metadata value yields an empty result set.

    Intent: metadata={"tags": {"project": "gamma"}} should not match either
    call since no 'project' has value 'gamma'.
    """
    c1, c2 = make_calls()
    store.save(c1)
    store.save(c2)

    tpl = Call(name=None, arguments=None, metadata={"tags": {"project": "gamma"}}, module=None, version=None, result=None)
    names = {c.name for c in store.query(tpl)}
    assert names == set(), (
        "No call has tags.project == 'gamma'; result set must be empty"
    )
