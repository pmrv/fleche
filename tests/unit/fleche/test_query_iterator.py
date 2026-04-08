import pytest
import pandas as pd

from fleche import fleche, cache
from fleche.call import Call, LazyCall, QueryCall
from fleche.caches import Cache
from fleche.query import QueryIterator
from fleche.storage import Memory


@pytest.fixture
def test_cache():
    return Cache(values=Memory({}), _calls=Memory({}))


def _make_cache_with_calls(*calls):
    """Helper: save given Call objects into a fresh in-memory cache and return it."""
    c = Cache(values=Memory({}), _calls=Memory({}))
    for call in calls:
        c.save(call)
    return c


# ---------------------------------------------------------------------------
# Basic iteration
# ---------------------------------------------------------------------------

def test_query_iterator_is_iterable(test_cache):
    """QueryIterator yields the LazyCall objects from the underlying iterable."""
    test_cache.save(Call(name="f", arguments={"x": 1}, result=10))
    test_cache.save(Call(name="f", arguments={"x": 2}, result=20))

    tpl = Call(name="f", arguments=None, metadata=None, module=None, version=None, result=None)
    it = test_cache.query(tpl)

    assert isinstance(it, QueryIterator)
    items = list(it)
    assert len(items) == 2
    for item in items:
        assert isinstance(item, LazyCall)
        assert item.name == "f"


def test_query_iterator_empty():
    """QueryIterator over an empty iterable yields nothing."""
    it = QueryIterator([])
    assert list(it) == []


def test_query_iterator_can_be_iterated_from_wrapper(test_cache):
    """The iterator returned by a fleche-decorated function's .query() method is a QueryIterator."""
    with cache(test_cache):
        @fleche
        def add(x, y):
            return x + y

        add(1, 2)
        add(3, 4)

        result = add.query()
        assert isinstance(result, QueryIterator)
        assert len(list(result)) == 2


# ---------------------------------------------------------------------------
# .results() convenience method
# ---------------------------------------------------------------------------

def test_query_iterator_results(test_cache):
    """results() yields the result values of each call."""
    test_cache.save(Call(name="f", arguments={"x": 1}, result=10))
    test_cache.save(Call(name="f", arguments={"x": 2}, result=20))

    tpl = Call(name="f", arguments=None, metadata=None, module=None, version=None, result=None)
    results = list(test_cache.query(tpl).results())
    assert sorted(results) == [10, 20]


def test_query_iterator_results_empty():
    """results() on an empty QueryIterator yields nothing."""
    assert list(QueryIterator([]).results()) == []


def test_query_iterator_results_from_wrapper(test_cache):
    """results() works correctly when the iterator comes from a fleche wrapper."""
    with cache(test_cache):
        @fleche
        def square(n):
            return n * n

        square(3)
        square(4)

        results = sorted(square.query().results())
        assert results == [9, 16]


# ---------------------------------------------------------------------------
# .table() — basic structure
# ---------------------------------------------------------------------------

def test_query_iterator_table_returns_dataframe(test_cache):
    """table() returns a pandas DataFrame."""
    test_cache.save(Call(name="f", arguments={"x": 1}, result=10))
    tpl = Call(name="f", arguments=None, metadata=None, module=None, version=None, result=None)
    df = test_cache.query(tpl).table()
    assert isinstance(df, pd.DataFrame)


def test_query_iterator_table_basic_columns(test_cache):
    """table() always has 'name' and 'module' columns."""
    test_cache.save(Call(name="my_func", arguments={"a": 1}, result=42, module="mymod"))
    tpl = Call(name="my_func", arguments=None, metadata=None, module=None, version=None, result=None)
    df = test_cache.query(tpl).table()
    assert "name" in df.columns
    assert "module" in df.columns


def test_query_iterator_table_index_is_lookup_key(test_cache):
    """The DataFrame index entries match each call's to_lookup_key()."""
    call1 = Call(name="f", arguments={"x": 1}, result=10)
    call2 = Call(name="f", arguments={"x": 2}, result=20)
    test_cache.save(call1)
    test_cache.save(call2)

    tpl = Call(name="f", arguments=None, metadata=None, module=None, version=None, result=None)
    df = test_cache.query(tpl).table()

    expected_keys = {str(call1.to_lookup_key()), str(call2.to_lookup_key())}
    assert set(df.index) == expected_keys


def test_query_iterator_table_no_result_by_default(test_cache):
    """result column is not present unless results=True is passed."""
    test_cache.save(Call(name="f", arguments={"x": 1}, result=99))
    tpl = Call(name="f", arguments=None, metadata=None, module=None, version=None, result=None)
    df = test_cache.query(tpl).table()
    assert "result" not in df.columns


def test_query_iterator_table_empty():
    """table() on an empty QueryIterator returns an empty DataFrame."""
    df = QueryIterator([]).table()
    assert isinstance(df, pd.DataFrame)
    assert len(df) == 0


# ---------------------------------------------------------------------------
# .table() — arguments parameter
# ---------------------------------------------------------------------------

def test_query_iterator_table_with_arguments(test_cache):
    """Requested argument names appear as columns in the DataFrame."""
    test_cache.save(Call(name="f", arguments={"x": 3, "y": 7}, result=10))
    tpl = Call(name="f", arguments=None, metadata=None, module=None, version=None, result=None)
    df = test_cache.query(tpl).table(arguments=["x", "y"])
    assert "x" in df.columns
    assert "y" in df.columns
    assert df["x"].iloc[0] == 3
    assert df["y"].iloc[0] == 7


def test_query_iterator_table_missing_argument_is_none(test_cache):
    """If a requested argument name does not exist on a call, the value is None."""
    test_cache.save(Call(name="f", arguments={"x": 1}, result=10))
    tpl = Call(name="f", arguments=None, metadata=None, module=None, version=None, result=None)
    df = test_cache.query(tpl).table(arguments=["nonexistent"])
    assert "nonexistent" in df.columns
    assert df["nonexistent"].iloc[0] is None


def test_query_iterator_table_argument_column_clash_prefixed(test_cache):
    """Arguments whose names clash with reserved columns are prefixed with 'a_'."""
    # 'name' and 'module' are reserved columns in the table
    test_cache.save(Call(name="f", arguments={"name": "clash_value"}, result=1))
    tpl = Call(name="f", arguments=None, metadata=None, module=None, version=None, result=None)
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
    tpl = Call(name="f", arguments=None, metadata=None, module=None, version=None, result=None)
    df = test_cache.query(tpl).table(results=True)
    assert "result" in df.columns
    assert df["result"].iloc[0] == 25


def test_query_iterator_table_results_multiple_calls(test_cache):
    """results=True works correctly when there are multiple calls."""
    test_cache.save(Call(name="f", arguments={"x": 1}, result=10))
    test_cache.save(Call(name="f", arguments={"x": 2}, result=20))
    tpl = Call(name="f", arguments=None, metadata=None, module=None, version=None, result=None)
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
    tpl = Call(name="f", arguments=None, metadata=None, module=None, version=None, result=None)
    df = test_cache.query(tpl).table()
    assert "elapsed" in df.columns
    assert df["elapsed"].iloc[0] == 1.5
    assert "unit" in df.columns
    assert df["unit"].iloc[0] == "s"


def test_query_iterator_table_no_metadata(test_cache):
    """Calls without metadata produce no extra columns."""
    test_cache.save(Call(name="f", arguments={"x": 1}, result=10, metadata={}))
    tpl = Call(name="f", arguments=None, metadata=None, module=None, version=None, result=None)
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

        df = multiply.query().table(arguments=["a", "b"], results=True)
        assert isinstance(df, pd.DataFrame)
        assert len(df) == 2
        assert set(df.columns) >= {"name", "a", "b", "result"}
        assert set(df["result"]) == {6, 20}


# ---------------------------------------------------------------------------
# Partial query binding through the wrapper
# ---------------------------------------------------------------------------

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
        results = list(bar.query(y=5))
        assert len(results) == 2

        # Querying for x=1: y and z are not specified so they're wildcards → 2 results
        results = list(bar.query(x=1))
        assert len(results) == 2


def test_query_preserves_order_with_partial():
    @fleche
    def order_func(a, b, c):
        return a

    call_obj = QueryCall.from_call(order_func, c=3, a=1)
    # The order of arguments should follow the function signature
    assert list(call_obj.arguments.keys()) == ["a", "b", "c"]
    assert call_obj.arguments == {"a": 1, "b": None, "c": 3}
