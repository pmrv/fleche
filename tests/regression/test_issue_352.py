"""Regression tests for issue #352.

Bug: table(arguments=...) silently drops (overwrites) arguments whose names clash
with keys produced by flattening metadata dicts into the row.

Root cause: in query.py, arguments are added to the row first (with clash detection
only against name/module/metadata/result), then metadata is flattened via
row.update(data), which overwrites any argument that shares a key with a metadata field.
"""

import pytest
from fleche.call import Call, QueryCall
from fleche.caches import Cache
from fleche.storage import ValueMemory, CallMemory


@pytest.fixture
def test_cache():
    return Cache(values=ValueMemory({}), calls=CallMemory({}))


def test_argument_clashing_with_metadata_key_not_silently_dropped(test_cache):
    """An argument whose name matches a flattened metadata key must not be overwritten.

    The argument value should be accessible — either under a prefixed 'a_<name>'
    column (consistent with how clashes with 'name'/'module' are handled) or the
    column should hold the argument value, not the metadata value.
    """
    call = Call(
        name="f",
        arguments={"elapsed": 42},        # argument named the same as a metadata field
        result=10,
        metadata={"timing": {"elapsed": 1.5}},  # metadata also produces 'elapsed'
    )
    test_cache.save(call)
    tpl = QueryCall(name="f", arguments=None, metadata=None, module=None, version=None, result=None)
    df = test_cache.query(tpl).table(arguments=["elapsed"])

    # The argument value (42) must not be silently replaced by the metadata value (1.5).
    # Consistent with the existing clash-handling for 'name'/'module', the argument
    # should appear under the 'a_elapsed' column.
    assert "a_elapsed" in df.columns, (
        "argument 'elapsed' should be prefixed as 'a_elapsed' when it clashes with a metadata key"
    )
    assert df["a_elapsed"].iloc[0] == 42, (
        f"expected argument value 42, got {df['a_elapsed'].iloc[0]!r}"
    )
    # The metadata value should still be present under the bare 'elapsed' column
    assert df["elapsed"].iloc[0] == 1.5


def test_argument_clashing_with_metadata_key_via_arguments_true(test_cache):
    """Same clash scenario with arguments=True (all arguments included)."""
    call = Call(
        name="f",
        arguments={"elapsed": 42},
        result=10,
        metadata={"timing": {"elapsed": 1.5}},
    )
    test_cache.save(call)
    tpl = QueryCall(name="f", arguments=None, metadata=None, module=None, version=None, result=None)
    df = test_cache.query(tpl).table(arguments=True)

    assert "a_elapsed" in df.columns
    assert df["a_elapsed"].iloc[0] == 42
    assert df["elapsed"].iloc[0] == 1.5
