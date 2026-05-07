import pytest
import pandas as pd

from fleche import fleche, cache
from fleche.call import Call, LazyCall, QueryCall
from fleche.caches import Cache
from fleche.query import QueryIterator
from fleche.storage import ValueMemory, CallMemory


@pytest.fixture
def test_cache():
    return Cache(values=ValueMemory({}), calls=CallMemory({}))


# ---------------------------------------------------------------------------
# Basic iteration
# ---------------------------------------------------------------------------

def test_query_iterator_is_iterable(test_cache):
    """QueryIterator yields the LazyCall objects from the underlying iterable."""
    test_cache.save(Call(name="f", arguments={"x": 1}, result=10))
    test_cache.save(Call(name="f", arguments={"x": 2}, result=20))

    tpl = QueryCall(name="f", arguments=None, metadata=None, module=None, version=None, result=None)
    it = test_cache.query(tpl)

    assert isinstance(it, QueryIterator)
    items = list(it)
    assert len(items) == 2
    for item in items:
        assert isinstance(item, LazyCall)
        assert item.name == "f"


def test_query_iterator_empty():
    """QueryIterator over an empty iterable yields nothing."""
    it = QueryIterator(lambda: [])
    assert list(it) == []


def test_query_iterator_is_re_iterable(test_cache):
    """Iterating a QueryIterator twice yields the same results both times."""
    test_cache.save(Call(name="f", arguments={"x": 1}, result=10))
    test_cache.save(Call(name="f", arguments={"x": 2}, result=20))
    tpl = QueryCall(name="f", arguments=None, metadata=None, module=None, version=None, result=None)
    qi = test_cache.query(tpl)
    first = sorted(c.arguments["x"] for c in qi)
    second = sorted(c.arguments["x"] for c in qi)
    assert first == second == [1, 2]


def test_query_iterator_reflects_cache_changes(test_cache):
    """Re-iterating a QueryIterator picks up calls added to the cache after it was created."""
    test_cache.save(Call(name="f", arguments={"x": 1}, result=10))
    tpl = QueryCall(name="f", arguments=None, metadata=None, module=None, version=None, result=None)
    qi = test_cache.query(tpl)

    first = sorted(c.arguments["x"] for c in qi)
    test_cache.save(Call(name="f", arguments={"x": 2}, result=20))
    second = sorted(c.arguments["x"] for c in qi)

    assert first == [1]
    assert second == [1, 2]


def test_query_iterator_can_be_iterated_from_wrapper(test_cache):
    """The iterator returned by a fleche-decorated function's .query() method is a QueryIterator."""
    with cache(test_cache):
        @fleche
        def add(x, y):
            return x + y

        add(1, 2)
        add(3, 4)

        result = add.fleche.query()
        assert isinstance(result, QueryIterator)
        assert len(list(result)) == 2


# ---------------------------------------------------------------------------
# .results() convenience method
# ---------------------------------------------------------------------------

def test_query_iterator_results(test_cache):
    """results() yields the result values of each call."""
    test_cache.save(Call(name="f", arguments={"x": 1}, result=10))
    test_cache.save(Call(name="f", arguments={"x": 2}, result=20))

    tpl = QueryCall(name="f", arguments=None, metadata=None, module=None, version=None, result=None)
    results = list(test_cache.query(tpl).results())
    assert sorted(results) == [10, 20]


def test_query_iterator_results_empty():
    """results() on an empty QueryIterator yields nothing."""
    assert list(QueryIterator(lambda: []).results()) == []


def test_query_iterator_results_from_wrapper(test_cache):
    """results() works correctly when the iterator comes from a fleche wrapper."""
    with cache(test_cache):
        @fleche
        def square(n):
            return n * n

        square(3)
        square(4)

        results = sorted(square.fleche.query().results())
        assert results == [9, 16]


# ---------------------------------------------------------------------------
# .table() — basic structure
# ---------------------------------------------------------------------------

def test_query_iterator_table_returns_dataframe(test_cache):
    """table() returns a pandas DataFrame."""
    test_cache.save(Call(name="f", arguments={"x": 1}, result=10))
    tpl = QueryCall(name="f", arguments=None, metadata=None, module=None, version=None, result=None)
    df = test_cache.query(tpl).table()
    assert isinstance(df, pd.DataFrame)


def test_query_iterator_table_basic_columns(test_cache):
    """table() always has 'name' and 'module' columns."""
    test_cache.save(Call(name="my_func", arguments={"a": 1}, result=42, module="mymod"))
    tpl = QueryCall(name="my_func", arguments=None, metadata=None, module=None, version=None, result=None)
    df = test_cache.query(tpl).table()
    assert "name" in df.columns
    assert "module" in df.columns


def test_query_iterator_table_index_is_lookup_key(test_cache):
    """The DataFrame index entries match each call's to_lookup_key()."""
    call1 = Call(name="f", arguments={"x": 1}, result=10)
    call2 = Call(name="f", arguments={"x": 2}, result=20)
    test_cache.save(call1)
    test_cache.save(call2)

    tpl = QueryCall(name="f", arguments=None, metadata=None, module=None, version=None, result=None)
    df = test_cache.query(tpl).table()

    expected_keys = {str(call1.to_lookup_key()), str(call2.to_lookup_key())}
    assert set(df.index) == expected_keys


def test_query_iterator_table_no_result_by_default(test_cache):
    """result column is not present unless results=True is passed."""
    test_cache.save(Call(name="f", arguments={"x": 1}, result=99))
    tpl = QueryCall(name="f", arguments=None, metadata=None, module=None, version=None, result=None)
    df = test_cache.query(tpl).table()
    assert "result" not in df.columns


def test_query_iterator_table_empty():
    """table() on an empty QueryIterator returns an empty DataFrame."""
    df = QueryIterator(lambda: []).table()
    assert isinstance(df, pd.DataFrame)
    assert len(df) == 0


# ---------------------------------------------------------------------------
# .table() — arguments parameter
# ---------------------------------------------------------------------------

def test_query_iterator_table_with_arguments(test_cache):
    """Requested argument names appear as columns in the DataFrame."""
    test_cache.save(Call(name="f", arguments={"x": 3, "y": 7}, result=10))
    tpl = QueryCall(name="f", arguments=None, metadata=None, module=None, version=None, result=None)
    df = test_cache.query(tpl).table(arguments=["x", "y"])
    assert "x" in df.columns
    assert "y" in df.columns
    assert df["x"].iloc[0] == 3
    assert df["y"].iloc[0] == 7


def test_query_iterator_table_arguments_single_string(test_cache):
    """A single string passed to arguments is treated as a one-element tuple."""
    test_cache.save(Call(name="f", arguments={"x": 3, "y": 7}, result=10))
    tpl = QueryCall(name="f", arguments=None, metadata=None, module=None, version=None, result=None)
    df = test_cache.query(tpl).table(arguments="x")
    assert "x" in df.columns
    assert df["x"].iloc[0] == 3
    assert "y" not in df.columns


def test_query_iterator_table_arguments_true(test_cache):
    """arguments=True adds all arguments as columns."""
    test_cache.save(Call(name="f", arguments={"x": 3, "y": 7}, result=10))
    tpl = QueryCall(name="f", arguments=None, metadata=None, module=None, version=None, result=None)
    df = test_cache.query(tpl).table(arguments=True)
    assert "x" in df.columns
    assert "y" in df.columns
    assert df["x"].iloc[0] == 3
    assert df["y"].iloc[0] == 7


def test_query_iterator_table_arguments_true_multiple_calls(test_cache):
    """arguments=True collects the union of argument names across all calls."""
    test_cache.save(Call(name="f", arguments={"x": 1, "y": 2}, result=10))
    test_cache.save(Call(name="f", arguments={"x": 3, "z": 4}, result=20))
    tpl = QueryCall(name="f", arguments=None, metadata=None, module=None, version=None, result=None)
    df = test_cache.query(tpl).table(arguments=True)
    assert "x" in df.columns
    assert "y" in df.columns
    assert "z" in df.columns


def test_query_iterator_table_missing_argument_is_none(test_cache):
    """If a requested argument name does not exist on a call, the value is None."""
    test_cache.save(Call(name="f", arguments={"x": 1}, result=10))
    tpl = QueryCall(name="f", arguments=None, metadata=None, module=None, version=None, result=None)
    df = test_cache.query(tpl).table(arguments=["nonexistent"])
    assert "nonexistent" in df.columns
    assert df["nonexistent"].iloc[0] is None


def test_query_iterator_table_argument_column_clash_prefixed(test_cache):
    """Arguments whose names clash with reserved columns are prefixed with 'a_'."""
    # 'name' and 'module' are reserved columns in the table
    test_cache.save(Call(name="f", arguments={"name": "clash_value"}, result=1))
    tpl = QueryCall(name="f", arguments=None, metadata=None, module=None, version=None, result=None)
    df = test_cache.query(tpl).table(arguments=["name"])
    # Original 'name' column should still hold the function name
    assert df["name"].iloc[0] == "f"
    # The argument should be under the prefixed column
    assert "a_name" in df.columns
    assert df["a_name"].iloc[0] == "clash_value"


# ---------------------------------------------------------------------------
# .table() — results parameter
# ---------------------------------------------------------------------------

def test_query_iterator_table_with_results(test_cache):
    """results=True adds a 'result' column to the DataFrame."""
    test_cache.save(Call(name="f", arguments={"x": 5}, result=25))
    tpl = QueryCall(name="f", arguments=None, metadata=None, module=None, version=None, result=None)
    df = test_cache.query(tpl).table(results=True)
    assert "result" in df.columns
    assert df["result"].iloc[0] == 25


def test_query_iterator_table_results_multiple_calls(test_cache):
    """results=True works correctly when there are multiple calls."""
    test_cache.save(Call(name="f", arguments={"x": 1}, result=10))
    test_cache.save(Call(name="f", arguments={"x": 2}, result=20))
    tpl = QueryCall(name="f", arguments=None, metadata=None, module=None, version=None, result=None)
    df = test_cache.query(tpl).table(results=True)
    assert set(df["result"]) == {10, 20}


# ---------------------------------------------------------------------------
# .table() — metadata
# ---------------------------------------------------------------------------

def test_query_iterator_table_metadata_flattened(test_cache):
    """Metadata dicts are flattened into top-level columns."""
    call = Call(
        name="f",
        arguments={"x": 1},
        result=42,
        metadata={"timing": {"elapsed": 1.5, "unit": "s"}},
    )
    test_cache.save(call)
    tpl = QueryCall(name="f", arguments=None, metadata=None, module=None, version=None, result=None)
    df = test_cache.query(tpl).table()
    assert "elapsed" in df.columns
    assert df["elapsed"].iloc[0] == 1.5
    assert "unit" in df.columns
    assert df["unit"].iloc[0] == "s"


def test_query_iterator_table_no_metadata(test_cache):
    """Calls without metadata produce no extra columns."""
    test_cache.save(Call(name="f", arguments={"x": 1}, result=10, metadata={}))
    tpl = QueryCall(name="f", arguments=None, metadata=None, module=None, version=None, result=None)
    df = test_cache.query(tpl).table()
    # Only standard columns expected
    assert set(df.columns) == {"name", "module"}


def test_query_iterator_table_end_to_end_via_wrapper(test_cache):
    """Integration: using .query().table() from a fleche-decorated function."""
    with cache(test_cache):
        @fleche
        def multiply(a, b):
            return a * b

        multiply(2, 3)
        multiply(4, 5)

        df = multiply.fleche.query().table(arguments=["a", "b"], results=True)
        assert isinstance(df, pd.DataFrame)
        assert len(df) == 2
        assert set(df.columns) >= {"name", "a", "b", "result"}
        assert set(df["result"]) == {6, 20}


# ---------------------------------------------------------------------------
# Partial query binding through the wrapper
# ---------------------------------------------------------------------------

def test_query_iterator_table_timestart_timestop_converted_to_datetime(test_cache):
    """timestart and timestop metadata columns are automatically converted to datetime."""
    import time
    t0 = time.time()
    call = Call(
        name="f",
        arguments={"x": 1},
        result=42,
        metadata={"runtime": {"timestart": t0, "timestop": t0 + 1.5, "walltime": 1.5}},
    )
    test_cache.save(call)
    tpl = QueryCall(name="f", arguments=None, metadata=None, module=None, version=None, result=None)
    df = test_cache.query(tpl).table()
    assert pd.api.types.is_datetime64_any_dtype(df["timestart"])
    assert pd.api.types.is_datetime64_any_dtype(df["timestop"])
    # Timestamps should be timezone-aware (local timezone)
    assert df["timestart"].dt.tz is not None
    assert df["timestop"].dt.tz is not None
    # walltime should remain a float
    assert pd.api.types.is_float_dtype(df["walltime"])


def test_query_partial_arguments(test_cache):
    with cache(test_cache):

        @fleche
        def bar(x, y, z=10):
            return x + y + z

        call_obj = QueryCall.from_call(bar, y=5)
        # Unspecified z is None (wildcard), default is NOT applied
        assert call_obj.arguments == {"x": None, "y": 5, "z": None}

        # Test that .query uses partial binding
        bar(1, 5, 10)
        bar(2, 5, 20)
        bar(1, 6, 10)

        # Querying for y=5: z is not specified so it's a wildcard → 2 results
        results = list(bar.fleche.query(y=5))
        assert len(results) == 2

        # Querying for x=1: y and z are not specified so they're wildcards → 2 results
        results = list(bar.fleche.query(x=1))
        assert len(results) == 2


def test_query_preserves_order_with_partial():
    @fleche
    def order_func(a, b, c):
        return a

    call_obj = QueryCall.from_call(order_func, c=3, a=1)
    # The order of arguments should follow the function signature
    assert list(call_obj.arguments.keys()) == ["a", "b", "c"]
    assert call_obj.arguments == {"a": 1, "b": None, "c": 3}


# ---------------------------------------------------------------------------
# .only()
# ---------------------------------------------------------------------------

def test_only_returns_single_call(test_cache):
    test_cache.save(Call(name="f", arguments={"x": 1}, result=10))
    tpl = QueryCall(name="f", arguments=None, metadata=None, module=None, version=None, result=None)
    c = test_cache.query(tpl).only()
    assert c.name == "f"


def test_only_raises_on_empty():
    with pytest.raises(IndexError):
        QueryIterator(lambda: []).only()


def test_only_raises_on_multiple(test_cache):
    test_cache.save(Call(name="f", arguments={"x": 1}, result=10))
    test_cache.save(Call(name="f", arguments={"x": 2}, result=20))
    tpl = QueryCall(name="f", arguments=None, metadata=None, module=None, version=None, result=None)
    with pytest.raises(ValueError):
        test_cache.query(tpl).only()


# ---------------------------------------------------------------------------
# .count() / .any() / .empty()
# ---------------------------------------------------------------------------

def test_count_returns_correct_number(test_cache):
    test_cache.save(Call(name="f", arguments={"x": 1}, result=10))
    test_cache.save(Call(name="f", arguments={"x": 2}, result=20))
    tpl = QueryCall(name="f", arguments=None, metadata=None, module=None, version=None, result=None)
    assert test_cache.query(tpl).count() == 2


def test_any_returns_call(test_cache):
    test_cache.save(Call(name="f", arguments={"x": 1}, result=10))
    tpl = QueryCall(name="f", arguments=None, metadata=None, module=None, version=None, result=None)
    result = test_cache.query(tpl).any()
    assert isinstance(result, LazyCall)


def test_any_returns_none_on_empty():
    assert QueryIterator(lambda: []).any() is None


def test_empty_true():
    assert QueryIterator(lambda: []).empty() is True


def test_empty_false(test_cache):
    test_cache.save(Call(name="f", arguments={"x": 1}, result=10))
    tpl = QueryCall(name="f", arguments=None, metadata=None, module=None, version=None, result=None)
    assert test_cache.query(tpl).empty() is False


# ---------------------------------------------------------------------------
# .take() / .skip()
# ---------------------------------------------------------------------------

def test_take_returns_first_n(test_cache):
    for i in range(5):
        test_cache.save(Call(name="f", arguments={"x": i}, result=i * 10))
    tpl = QueryCall(name="f", arguments=None, metadata=None, module=None, version=None, result=None)
    calls = list(test_cache.query(tpl))
    qi = QueryIterator(lambda: iter(calls))
    assert list(qi.take(3)) == calls[:3]


def test_take_more_than_available(test_cache):
    test_cache.save(Call(name="f", arguments={"x": 1}, result=10))
    tpl = QueryCall(name="f", arguments=None, metadata=None, module=None, version=None, result=None)
    assert len(list(test_cache.query(tpl).take(10))) == 1


def test_take_zero(test_cache):
    test_cache.save(Call(name="f", arguments={"x": 1}, result=10))
    test_cache.save(Call(name="f", arguments={"x": 2}, result=20))
    tpl = QueryCall(name="f", arguments=None, metadata=None, module=None, version=None, result=None)
    assert list(test_cache.query(tpl).take(0)) == []


def test_skip_drops_first_n(test_cache):
    for i in range(5):
        test_cache.save(Call(name="f", arguments={"x": i}, result=i * 10))
    tpl = QueryCall(name="f", arguments=None, metadata=None, module=None, version=None, result=None)
    calls = list(test_cache.query(tpl))
    qi = QueryIterator(lambda: iter(calls))
    assert list(qi.skip(2)) == calls[2:]


def test_skip_more_than_available(test_cache):
    test_cache.save(Call(name="f", arguments={"x": 1}, result=10))
    test_cache.save(Call(name="f", arguments={"x": 2}, result=20))
    tpl = QueryCall(name="f", arguments=None, metadata=None, module=None, version=None, result=None)
    assert list(test_cache.query(tpl).skip(100)) == []


# ---------------------------------------------------------------------------
# .filter()
# ---------------------------------------------------------------------------

def test_filter_keeps_matching(test_cache):
    test_cache.save(Call(name="f", arguments={"x": 1}, result=10))
    test_cache.save(Call(name="f", arguments={"x": 2}, result=20))
    test_cache.save(Call(name="f", arguments={"x": 3}, result=30))
    tpl = QueryCall(name="f", arguments=None, metadata=None, module=None, version=None, result=None)
    results = list(test_cache.query(tpl).filter(lambda c: c.arguments["x"] > 1))
    assert len(results) == 2
    for c in results:
        assert c.arguments["x"] > 1


def test_filter_returns_query_iterator(test_cache):
    test_cache.save(Call(name="f", arguments={"x": 1}, result=10))
    tpl = QueryCall(name="f", arguments=None, metadata=None, module=None, version=None, result=None)
    assert isinstance(test_cache.query(tpl).filter(lambda c: True), QueryIterator)


def test_filter_all_excluded(test_cache):
    test_cache.save(Call(name="f", arguments={"x": 1}, result=10))
    test_cache.save(Call(name="f", arguments={"x": 2}, result=20))
    tpl = QueryCall(name="f", arguments=None, metadata=None, module=None, version=None, result=None)
    assert list(test_cache.query(tpl).filter(lambda c: False)) == []


# ---------------------------------------------------------------------------
# .sorted()
# ---------------------------------------------------------------------------

def test_sorted_by_argument_name(test_cache):
    test_cache.save(Call(name="f", arguments={"x": 3}, result=30))
    test_cache.save(Call(name="f", arguments={"x": 1}, result=10))
    test_cache.save(Call(name="f", arguments={"x": 2}, result=20))
    tpl = QueryCall(name="f", arguments=None, metadata=None, module=None, version=None, result=None)
    xs = [c.arguments["x"] for c in test_cache.query(tpl).sorted("x")]
    assert xs == [1, 2, 3]


def test_sorted_by_callable(test_cache):
    test_cache.save(Call(name="f", arguments={"x": 3}, result=30))
    test_cache.save(Call(name="f", arguments={"x": 1}, result=10))
    tpl = QueryCall(name="f", arguments=None, metadata=None, module=None, version=None, result=None)
    xs = [c.arguments["x"] for c in test_cache.query(tpl).sorted(key=lambda c: c.arguments["x"])]
    assert xs == [1, 3]


def test_sorted_reverse(test_cache):
    test_cache.save(Call(name="f", arguments={"x": 1}, result=10))
    test_cache.save(Call(name="f", arguments={"x": 2}, result=20))
    tpl = QueryCall(name="f", arguments=None, metadata=None, module=None, version=None, result=None)
    xs = [c.arguments["x"] for c in test_cache.query(tpl).sorted("x", reverse=True)]
    assert xs == [2, 1]


def test_sorted_returns_query_iterator(test_cache):
    test_cache.save(Call(name="f", arguments={"x": 1}, result=10))
    tpl = QueryCall(name="f", arguments=None, metadata=None, module=None, version=None, result=None)
    assert isinstance(test_cache.query(tpl).sorted("x"), QueryIterator)


# ---------------------------------------------------------------------------
# .unique()
# ---------------------------------------------------------------------------

def test_unique_argument_name(test_cache):
    test_cache.save(Call(name="f", arguments={"x": 1, "y": 1}, result=10))
    test_cache.save(Call(name="f", arguments={"x": 1, "y": 2}, result=20))
    test_cache.save(Call(name="f", arguments={"x": 2, "y": 3}, result=30))
    tpl = QueryCall(name="f", arguments=None, metadata=None, module=None, version=None, result=None)
    unique = list(test_cache.query(tpl).unique("x"))
    xs = [c.arguments["x"] for c in unique]
    assert len(unique) == 2
    assert set(xs) == {1, 2}


def test_unique_callable(test_cache):
    # Use distinct versions so both x=1 calls produce different cache entries
    test_cache.save(Call(name="f", arguments={"x": 1}, result=10, version=1))
    test_cache.save(Call(name="f", arguments={"x": 1}, result=10, version=2))
    test_cache.save(Call(name="f", arguments={"x": 2}, result=20))
    tpl = QueryCall(name="f", arguments=None, metadata=None, module=None, version=None, result=None)
    all_calls = list(test_cache.query(tpl))
    assert len(all_calls) == 3, "both x=1 calls must be stored as separate entries"
    unique = list(QueryIterator(lambda: iter(all_calls)).unique(lambda c: c.arguments["x"]))
    assert len(unique) == 2


def test_unique_returns_query_iterator(test_cache):
    test_cache.save(Call(name="f", arguments={"x": 1}, result=10))
    tpl = QueryCall(name="f", arguments=None, metadata=None, module=None, version=None, result=None)
    assert isinstance(test_cache.query(tpl).unique("x"), QueryIterator)


# ---------------------------------------------------------------------------
# .groupby()
# ---------------------------------------------------------------------------

def test_groupby_argument_name(test_cache):
    test_cache.save(Call(name="f", arguments={"x": 1, "y": 1}, result=10))
    test_cache.save(Call(name="f", arguments={"x": 1, "y": 2}, result=20))
    test_cache.save(Call(name="f", arguments={"x": 2, "y": 3}, result=30))
    tpl = QueryCall(name="f", arguments=None, metadata=None, module=None, version=None, result=None)
    groups = test_cache.query(tpl).groupby("x")
    assert set(groups.keys()) == {1, 2}
    assert len(list(groups[1])) == 2
    assert len(list(groups[2])) == 1


def test_groupby_callable(test_cache):
    test_cache.save(Call(name="f", arguments={"x": 1}, result=10))
    test_cache.save(Call(name="f", arguments={"x": 2}, result=20))
    tpl = QueryCall(name="f", arguments=None, metadata=None, module=None, version=None, result=None)
    groups = test_cache.query(tpl).groupby(lambda c: c.arguments["x"] % 2)
    assert set(groups.keys()) == {0, 1}


def test_groupby_returns_query_iterators(test_cache):
    test_cache.save(Call(name="f", arguments={"x": 1}, result=10))
    tpl = QueryCall(name="f", arguments=None, metadata=None, module=None, version=None, result=None)
    groups = test_cache.query(tpl).groupby("x")
    for v in groups.values():
        assert isinstance(v, QueryIterator)


# ---------------------------------------------------------------------------
# .latest() / .oldest()
# ---------------------------------------------------------------------------

def test_latest_returns_most_recent(test_cache):
    test_cache.save(Call(name="f", arguments={"x": 1}, result=10, metadata={"runtime": {"timestop": 100.0}}))
    test_cache.save(Call(name="f", arguments={"x": 2}, result=20, metadata={"runtime": {"timestop": 200.0}}))
    test_cache.save(Call(name="f", arguments={"x": 3}, result=30, metadata={"runtime": {"timestop": 50.0}}))
    tpl = QueryCall(name="f", arguments=None, metadata=None, module=None, version=None, result=None)
    all_calls = list(test_cache.query(tpl))
    expected = max(all_calls, key=lambda c: c.metadata["runtime"]["timestop"])
    result = test_cache.query(tpl).latest()
    assert result.to_lookup_key() == expected.to_lookup_key()


def test_oldest_returns_earliest(test_cache):
    test_cache.save(Call(name="f", arguments={"x": 1}, result=10, metadata={"runtime": {"timestop": 100.0}}))
    test_cache.save(Call(name="f", arguments={"x": 2}, result=20, metadata={"runtime": {"timestop": 200.0}}))
    test_cache.save(Call(name="f", arguments={"x": 3}, result=30, metadata={"runtime": {"timestop": 50.0}}))
    tpl = QueryCall(name="f", arguments=None, metadata=None, module=None, version=None, result=None)
    all_calls = list(test_cache.query(tpl))
    expected = min(all_calls, key=lambda c: c.metadata["runtime"]["timestop"])
    result = test_cache.query(tpl).oldest()
    assert result.to_lookup_key() == expected.to_lookup_key()


def test_latest_raises_on_empty():
    with pytest.raises(IndexError):
        QueryIterator(lambda: []).latest()


def test_oldest_raises_on_empty():
    with pytest.raises(IndexError):
        QueryIterator(lambda: []).oldest()


# ---------------------------------------------------------------------------
# .evict()
# ---------------------------------------------------------------------------

def test_evict_removes_calls(test_cache):
    test_cache.save(Call(name="f", arguments={"x": 1}, result=10))
    test_cache.save(Call(name="f", arguments={"x": 2}, result=20))
    tpl = QueryCall(name="f", arguments=None, metadata=None, module=None, version=None, result=None)
    assert test_cache.query(tpl).count() == 2
    test_cache.query(tpl).evict()
    assert test_cache.query(tpl).count() == 0


def test_evict_only_removes_matched(test_cache):
    test_cache.save(Call(name="f", arguments={"x": 1}, result=10))
    test_cache.save(Call(name="g", arguments={"x": 1}, result=10))
    tpl_f = QueryCall(name="f", arguments=None, metadata=None, module=None, version=None, result=None)
    tpl_g = QueryCall(name="g", arguments=None, metadata=None, module=None, version=None, result=None)
    test_cache.query(tpl_f).evict()
    assert test_cache.query(tpl_f).count() == 0
    assert test_cache.query(tpl_g).count() == 1
