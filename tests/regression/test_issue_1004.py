"""Regression test for issue #1004: a DataFrame with an object column of arrays.

``pd.util.hash_pandas_object`` factorizes object columns first, which raises on
unhashable elements, so saving such a frame through a destructuring value store
raised ``TypeError`` instead of caching the call.
"""

import numpy as np
import pandas as pd
import pytest

import fleche as fl
from fleche.caches import Cache
from fleche.config import cache_from_config
from fleche.storage.memory import CallMemory, ValueMemory


def _frame(scale):
    df = pd.DataFrame({"x": [1.0, 2.0]})
    df["v"] = [np.zeros(3), scale * np.ones(3)]
    return df


@pytest.mark.parametrize("calls", ["sql", "dill"])
def test_dataframe_with_array_column_is_cached(tmp_path, calls):
    pytest.importorskip("dill")
    if calls == "sql":
        pytest.importorskip("sqlalchemy")
        calls_config = {"type": "sql", "url": str(tmp_path / "calls.db")}
    else:
        calls_config = {"type": "dill", "root": str(tmp_path / "calls")}
    config = {
        "values": {"type": "dill", "root": str(tmp_path / "values"), "remaining_depth": 2},
        "calls": calls_config,
    }

    runs = []

    @fl.fleche()
    def f(scale):
        runs.append(scale)
        return _frame(scale)

    with fl.cache(cache_from_config(config)):
        first = f(1.0)
        again = f(1.0)
        other = f(2.0)

    assert runs == [1.0, 2.0]
    pd.testing.assert_frame_equal(first, _frame(1.0))
    pd.testing.assert_frame_equal(again, _frame(1.0))
    pd.testing.assert_frame_equal(other, _frame(2.0))


def test_dataframe_with_array_column_as_argument_hits():
    runs = []

    @fl.fleche()
    def g(df):
        runs.append(1)
        return float(sum(v.sum() for v in df["v"]))

    with fl.cache(Cache(values=ValueMemory({}), calls=CallMemory({}))):
        assert g(_frame(1.0)) == 3.0
        assert g(_frame(1.0)) == 3.0
        assert g(_frame(2.0)) == 6.0

    assert len(runs) == 2
