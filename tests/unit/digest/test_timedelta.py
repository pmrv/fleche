"""Timedelta digests: each library's timedeltas by their exact length, apart from
every other library's and from numbers."""

import datetime

import numpy as np
import pandas as pd
import pytest
from hypothesis import given
from hypothesis import strategies as st

from fleche.digest import digest

# Attoseconds per fixed numpy unit, written out independently of fleche._numpy.
AS_PER_UNIT = {
    "W": 604800 * 10**18,
    "D": 86400 * 10**18,
    "h": 3600 * 10**18,
    "m": 60 * 10**18,
    "s": 10**18,
    "ms": 10**15,
    "us": 10**12,
    "ns": 10**9,
    "ps": 10**6,
    "fs": 10**3,
    "as": 1,
}
INT64_MAX = 2**63 - 1


def test_unit_table_matches_numpy():
    for unit, n in AS_PER_UNIT.items():
        if n >= 10**18:
            # Whole seconds; in attoseconds these overflow numpy's int64.
            assert np.timedelta64(1, unit) == np.timedelta64(n // 10**18, "s")
        else:
            assert np.timedelta64(1, unit) == np.timedelta64(n, "as")


# --- across libraries ---------------------------------------------------------


@pytest.mark.parametrize("seconds", [0, 5, -5])
def test_libraries_digest_apart(seconds):
    values = [
        datetime.timedelta(seconds=seconds),
        pd.Timedelta(seconds=seconds),
        np.timedelta64(seconds, "s"),
    ]
    assert len({digest(v) for v in values}) == 3


@pytest.mark.parametrize(
    "value",
    [datetime.timedelta(seconds=5), pd.Timedelta("5s"), np.timedelta64(5, "s"), np.timedelta64(5)],
    ids=repr,
)
def test_timedeltas_never_digest_as_numbers(value):
    # numpy registers timedelta64 as numbers.Integral and calls
    # np.timedelta64(5, "s") == 5.
    assert digest(value) not in {digest(5), digest(5.0), digest(5 * 10**18), digest(0)}


# --- datetime.timedelta -------------------------------------------------------


@pytest.mark.parametrize(
    "a, b",
    [
        (datetime.timedelta(hours=1), datetime.timedelta(minutes=60)),
        (datetime.timedelta(days=1), datetime.timedelta(seconds=86400)),
        (datetime.timedelta(milliseconds=1), datetime.timedelta(microseconds=1000)),
        (datetime.timedelta(days=-1, seconds=86399), datetime.timedelta(seconds=-1)),
    ],
)
def test_equal_datetime_timedeltas_digest_equal(a, b):
    assert a == b
    assert digest(a) == digest(b)


@pytest.mark.parametrize(
    "a, b",
    [
        (datetime.timedelta(seconds=1), datetime.timedelta(seconds=2)),
        (datetime.timedelta(seconds=1), datetime.timedelta(seconds=-1)),
        # total_seconds(), the old digest, is a float and merged these.
        (
            datetime.timedelta(days=300 * 365, microseconds=1),
            datetime.timedelta(days=300 * 365, microseconds=2),
        ),
        (datetime.timedelta.max, datetime.timedelta.max - datetime.timedelta.resolution),
    ],
)
def test_unequal_datetime_timedeltas_digest_apart(a, b):
    assert a != b
    assert digest(a) != digest(b)


@given(st.timedeltas(), st.timedeltas())
def test_datetime_timedeltas_digest_equal_iff_equal(a, b):
    assert (digest(a) == digest(b)) == (a == b)


def test_timezone_digests_its_offset():
    five = datetime.timezone(datetime.timedelta(hours=5))
    assert digest(five) == digest(datetime.timezone(datetime.timedelta(minutes=300), "X"))
    assert digest(five) != digest(datetime.timezone(datetime.timedelta(hours=5, microseconds=1)))
    assert digest(five) != digest(datetime.timedelta(hours=5))


# --- pd.Timedelta -------------------------------------------------------------


@pytest.mark.parametrize(
    "a, b",
    [
        (pd.Timedelta("5s"), pd.Timedelta(5000, "ms")),
        (pd.Timedelta("5s"), pd.Timedelta("5s").as_unit("s")),
        (pd.Timedelta("1D"), pd.Timedelta(hours=24).as_unit("ms")),
        (pd.Timedelta(-1, "ns"), pd.Timedelta(-1, "ns").as_unit("ns")),
    ],
)
def test_equal_pandas_timedeltas_digest_equal_whatever_their_unit(a, b):
    assert a == b
    assert digest(a) == digest(b)


@pytest.mark.parametrize(
    "a, b",
    [
        # total_seconds(), the old digest, is a float and merged these.
        (pd.Timedelta(days=50, nanoseconds=1), pd.Timedelta(days=50, nanoseconds=2)),
        (pd.Timedelta("5s"), pd.Timedelta("5ms")),
        (pd.Timedelta.max, pd.Timedelta.max - pd.Timedelta(1, "ns")),
    ],
)
def test_unequal_pandas_timedeltas_digest_apart(a, b):
    assert a != b
    assert digest(a) != digest(b)


def test_second_unit_pandas_timedelta_beyond_int64_nanoseconds():
    # .value would overflow; the digest goes through the stored unit.
    big = pd.Timedelta(np.timedelta64(10**12, "s"))
    assert digest(big) != digest(pd.Timedelta(np.timedelta64(10**12 - 1, "s")))


def test_pandas_nat_keeps_its_own_digest():
    # pd.NaT also stands for missing datetimes; it is not a timedelta.
    assert pd.Timedelta("NaT") is pd.NaT
    assert digest(pd.NaT) != digest(np.timedelta64("NaT", "ns"))


def test_object_column_of_pandas_timedeltas():
    a = pd.Series([pd.Timedelta("1s"), "x"], dtype=object)
    b = pd.Series([pd.Timedelta("2s"), "x"], dtype=object)
    assert digest(a) != digest(b)


# --- np.timedelta64 -----------------------------------------------------------


def attoseconds(value: np.timedelta64) -> int:
    unit, multiple = np.datetime_data(value.dtype)
    return int(value.view(np.int64)) * multiple * AS_PER_UNIT[unit]


@pytest.mark.parametrize(
    "a, b",
    [
        (np.timedelta64(5, "s"), np.timedelta64(5000, "ms")),
        (np.timedelta64(5, "s"), np.timedelta64(500, "10ms")),
        (np.timedelta64(1, "W"), np.timedelta64(7, "D")),
        (np.timedelta64(1, "D"), np.timedelta64(24, "h")),
        (np.timedelta64(1, "Y"), np.timedelta64(12, "M")),
        (np.timedelta64(0, "s"), np.timedelta64(0, "as")),
    ],
)
def test_equal_timedelta64_digest_equal_whatever_their_unit(a, b):
    assert digest(a) == digest(b)


@pytest.mark.parametrize(
    "a, b",
    [
        (np.timedelta64(5, "s"), np.timedelta64(5, "ms")),
        (np.timedelta64(1, "M"), np.timedelta64(30, "D")),  # months have no length
        (np.timedelta64(0, "M"), np.timedelta64(0, "D")),
        (np.timedelta64(1, "Y"), np.timedelta64(365, "D")),
        (np.timedelta64(5), np.timedelta64(5, "s")),  # numpy calls these equal
        (np.timedelta64("NaT", "s"), np.timedelta64(0, "s")),
        (np.timedelta64(INT64_MAX, "ns"), np.timedelta64(INT64_MAX - 1, "ns")),
    ],
)
def test_unequal_timedelta64_digest_apart(a, b):
    assert digest(a) != digest(b)


def test_numpy_equality_is_not_the_reference():
    # numpy compares across units in int64 after casting to the finer unit,
    # which can wrap; the digest follows the exact length.
    big = np.timedelta64(2**62, "s")
    ns = (2**62 * 10**9) % 2**64  # its nanoseconds, wrapped into int64
    wrapped = np.timedelta64(ns - 2**64 if ns >= 2**63 else ns, "ns")
    assert digest(big) != digest(wrapped)


FIXED_UNITS = [*AS_PER_UNIT, "10ms", "25W", "3us"]


@given(
    st.sampled_from(FIXED_UNITS),
    st.integers(-INT64_MAX, INT64_MAX),
    st.sampled_from(FIXED_UNITS),
    st.integers(-INT64_MAX, INT64_MAX),
)
def test_timedelta64_digest_equal_iff_same_length(u1, c1, u2, c2):
    a, b = np.timedelta64(c1, u1), np.timedelta64(c2, u2)
    assert (digest(a) == digest(b)) == (attoseconds(a) == attoseconds(b))


@given(st.sampled_from(FIXED_UNITS), st.integers(-(10**6), 10**6))
def test_whole_units_digest_alike_in_every_finer_unit(unit, count):
    value = np.timedelta64(count, unit)
    length = attoseconds(value)
    for finer, n in AS_PER_UNIT.items():
        if length % n == 0 and abs(length // n) <= INT64_MAX:
            assert digest(np.timedelta64(length // n, finer)) == digest(value)


@pytest.mark.parametrize("unit", [*AS_PER_UNIT, "Y", "M", "10ms", "generic"])
def test_nat_digests_alike_in_every_unit(unit):
    nat = np.timedelta64("NaT") if unit == "generic" else np.timedelta64("NaT", unit)
    assert digest(nat) == digest(np.timedelta64("NaT", "ns"))


def test_generic_unit_digests_by_its_count():
    assert digest(np.timedelta64(5)) == digest(np.timedelta64(5))
    assert digest(np.timedelta64(5)) != digest(np.timedelta64(6))
    assert all(digest(np.timedelta64(5)) != digest(np.timedelta64(5, u)) for u in AS_PER_UNIT)


def test_timedelta64_inside_containers():
    assert digest([np.timedelta64(5, "s")]) == digest([np.timedelta64(5000, "ms")])
    assert digest({"t": np.timedelta64(5, "s")}) != digest({"t": np.timedelta64(5, "ms")})
