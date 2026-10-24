"""Digests of durations: ``datetime.timedelta``, ``pd.Timedelta``, ``np.timedelta64``.

The reference is the exact length of the duration, held here as an integer
count of attoseconds computed independently of :mod:`fleche._timedelta`.
"""

import datetime
import itertools
import math
from fractions import Fraction

import numpy as np
import pandas as pd
import pytest
from hypothesis import assume, example, given
from hypothesis import strategies as st

from fleche._hashing import new_hash
from fleche.digest import digest

INT64_MAX = 2**63 - 1
NAT = -(2**63)

# Seconds per fixed numpy unit, checked against numpy below.
SECONDS = {
    "W": Fraction(7 * 86400),
    "D": Fraction(86400),
    "h": Fraction(3600),
    "m": Fraction(60),
    "s": Fraction(1),
    "ms": Fraction(1, 10**3),
    "us": Fraction(1, 10**6),
    "ns": Fraction(1, 10**9),
    "ps": Fraction(1, 10**12),
    "fs": Fraction(1, 10**15),
    "as": Fraction(1, 10**18),
}
ATTOSECONDS = {unit: int(s * 10**18) for unit, s in SECONDS.items()}
MULTIPLIERS = (1, 2, 3, 10, 25)


def test_unit_table_matches_numpy():
    units = list(SECONDS)
    for coarse, fine in itertools.pairwise(units):
        ratio = SECONDS[coarse] / SECONDS[fine]
        assert ratio.denominator == 1
        assert np.timedelta64(1, coarse) == np.timedelta64(int(ratio), fine)


def attoseconds(value) -> int:
    """Exact length of a fixed-length duration, in attoseconds."""
    if isinstance(value, pd.Timedelta):
        value = value.to_timedelta64()
    if isinstance(value, np.timedelta64):
        unit, multiple = np.datetime_data(value.dtype)
        return int(value.astype(np.int64)) * multiple * ATTOSECONDS[unit]
    return (
        (value.days * 86400 + value.seconds) * 10**6 + value.microseconds
    ) * ATTOSECONDS["us"]


# --- strategies ---

counts = st.one_of(
    st.integers(-3, 3),
    st.integers(-(10**6), 10**6),
    st.integers(-INT64_MAX, INT64_MAX),
)
fixed_units = st.tuples(st.sampled_from(MULTIPLIERS), st.sampled_from(list(SECONDS)))


@st.composite
def fixed_timedelta64(draw):
    multiple, unit = draw(fixed_units)
    return np.timedelta64(draw(counts), f"{multiple}{unit}")


@st.composite
def pandas_timedeltas(draw):
    # pd.Timedelta holds s, ms, us or ns.
    unit = draw(st.sampled_from(["s", "ms", "us", "ns"]))
    count = draw(counts)
    try:
        return pd.Timedelta(np.timedelta64(count, unit))
    except (OverflowError, ValueError):
        assume(False)


fixed_durations = st.one_of(
    fixed_timedelta64(),
    st.timedeltas(),
    pandas_timedeltas(),
)


def representations(total: int):
    """Every value of the three types, in every unit, of length *total* attoseconds."""
    for multiple in MULTIPLIERS:
        for unit, per in ATTOSECONDS.items():
            q, r = divmod(total, multiple * per)
            if r == 0 and -INT64_MAX <= q <= INT64_MAX:
                yield np.timedelta64(q, f"{multiple}{unit}")
    us, r = divmod(total, ATTOSECONDS["us"])
    if r == 0:
        try:
            yield datetime.timedelta(microseconds=us)
        except OverflowError:
            pass
    ns, r = divmod(total, ATTOSECONDS["ns"])
    if r == 0 and -INT64_MAX <= ns <= INT64_MAX:
        yield pd.Timedelta(ns, unit="ns")


# --- equality across types and units ---


@pytest.mark.parametrize(
    "values",
    [
        (
            datetime.timedelta(seconds=5),
            pd.Timedelta("5s"),
            pd.Timedelta(np.timedelta64(5, "s")),
            np.timedelta64(5, "s"),
            np.timedelta64(5000, "ms"),
            np.timedelta64(500, "10ms"),
            np.timedelta64(5 * 10**18, "as"),
        ),
        (np.timedelta64(1, "W"), np.timedelta64(7, "D"), datetime.timedelta(weeks=1)),
        (np.timedelta64(1, "h"), np.timedelta64(60, "m"), np.timedelta64(2, "30m")),
        (np.timedelta64(1, "ps"), np.timedelta64(1000, "fs"), np.timedelta64(10**6, "as")),
        (
            datetime.timedelta(seconds=-5),
            pd.Timedelta(-5, unit="s"),
            np.timedelta64(-5000, "ms"),
        ),
        (datetime.timedelta(0), pd.Timedelta(0), np.timedelta64(0, "as"), np.timedelta64(0, "W")),
        (pd.Timedelta.max, np.timedelta64(INT64_MAX, "ns")),
        (pd.Timedelta.min, np.timedelta64(-INT64_MAX, "ns")),
        (datetime.timedelta.min, np.timedelta64(-999999999, "D")),
        # Beyond int64 nanoseconds, where pd.Timedelta.value overflows.
        (pd.Timedelta(np.timedelta64(10**15, "s")), np.timedelta64(10**15, "s")),
    ],
    ids=repr,
)
def test_equal_durations_digest_equal(values):
    # Not checked with ==, which misses some of these (see below).
    assert len({attoseconds(v) for v in values}) == 1
    assert len({digest(v) for v in values}) == 1


def _compare(a, b):
    try:
        return bool(a == b)
    except (OverflowError, ValueError) as e:
        return type(e)


@pytest.mark.parametrize(
    "a, b, numpy_says",
    [
        # numpy finds no int64 unit both fit in.
        (np.timedelta64(5, "s"), np.timedelta64(5 * 10**18, "as"), OverflowError),
        (datetime.timedelta(seconds=5), np.timedelta64(5 * 10**18, "as"), False),
        # pandas ignores the multiplier of a multiplied unit, and has no "as".
        (pd.Timedelta("5s"), np.timedelta64(500, "10ms"), False),
        (pd.Timedelta("5s"), np.timedelta64(5 * 10**18, "as"), ValueError),
    ],
    ids=repr,
)
def test_equal_lengths_digest_equal_where_eq_misses_them(a, b, numpy_says):
    assert _compare(a, b) == numpy_says
    assert digest(a) == digest(b)


@given(fixed_durations)
@example(datetime.timedelta.max)
@example(datetime.timedelta.min)
@example(pd.Timedelta.max)
@example(np.timedelta64(INT64_MAX, "W"))
@example(np.timedelta64(-INT64_MAX, "25W"))
def test_every_representation_digests_alike(value):
    expected = digest(value)
    for other in representations(attoseconds(value)):
        assert digest(other) == expected, other


@given(st.sampled_from(list(SECONDS)), st.integers(-(10**6), 10**6))
def test_every_representation_of_whole_units_digests_alike(unit, count):
    # Whole units of a coarse unit have representations in many others.
    value = np.timedelta64(count, unit)
    expected = digest(value)
    for other in representations(attoseconds(value)):
        assert digest(other) == expected, other


# --- unequal durations ---


@pytest.mark.parametrize(
    "a, b",
    [
        # total_seconds() merged these: both are 4320000.000000001 as a float.
        (pd.Timedelta(days=50, nanoseconds=1), pd.Timedelta(days=50, nanoseconds=2)),
        (np.timedelta64(5, "s"), np.timedelta64(5, "ms")),
        (np.timedelta64(1, "M"), np.timedelta64(1, "D")),
        (np.timedelta64(0, "M"), np.timedelta64(0, "D")),
        (np.timedelta64(1, "Y"), np.timedelta64(365, "D")),
        (np.timedelta64(1, "as"), np.timedelta64(0, "as")),
        (np.timedelta64(5, "s"), np.timedelta64(-5, "s")),
        (datetime.timedelta.max, datetime.timedelta.max - datetime.timedelta.resolution),
        (pd.Timedelta.max, pd.Timedelta.max - pd.Timedelta(1)),
        (np.timedelta64(INT64_MAX, "W"), np.timedelta64(INT64_MAX - 1, "W")),
    ],
    ids=repr,
)
def test_unequal_durations_digest_apart(a, b):
    assert digest(a) != digest(b)


@given(fixed_durations, fixed_durations)
def test_digests_equal_exactly_when_lengths_equal(a, b):
    assert (digest(a) == digest(b)) == (attoseconds(a) == attoseconds(b))


@given(fixed_timedelta64(), fixed_timedelta64())
def test_numpy_equality_agrees_where_it_cannot_overflow(a, b):
    # numpy compares in the gcd of the two units, in int64.
    (ua, ma), (ub, mb) = np.datetime_data(a.dtype), np.datetime_data(b.dtype)
    fa, fb = ma * ATTOSECONDS[ua], mb * ATTOSECONDS[ub]
    g = math.gcd(fa, fb)
    va, vb = int(a.astype(np.int64)), int(b.astype(np.int64))
    assume(abs(va * fa // g) <= INT64_MAX and abs(vb * fb // g) <= INT64_MAX)
    numpy_says = _compare(a, b)
    # numpy also refuses unit pairs whose conversion it cannot do in int64.
    assume(numpy_says is not OverflowError)
    assert numpy_says == (digest(a) == digest(b))


def test_numpy_overflowing_equality_is_not_the_reference():
    # numpy casts 2**62 s to ns in int64 and wraps; the lengths differ.
    a = np.timedelta64(2**62, "s")
    wrapped = (2**62 * 10**9 + 2**63) % 2**64 - 2**63
    b = np.timedelta64(wrapped, "ns")
    assert a == b
    assert digest(a) != digest(b)


# --- apart from plain numbers ---


@given(fixed_durations)
@example(np.timedelta64(5, "s"))
@example(np.timedelta64(0, "s"))
def test_durations_never_digest_as_numbers(value):
    total = attoseconds(value)
    numbers = {total, Fraction(total, 10**18), float(Fraction(total, 10**18))}
    if isinstance(value, np.timedelta64):
        numbers.add(int(value.astype(np.int64)))
    if isinstance(value, datetime.timedelta):
        numbers.add(value.total_seconds())
    assert digest(value) not in {digest(n) for n in numbers}


def test_numpy_equal_number_digests_apart():
    assert np.timedelta64(5, "s") == 5
    assert digest(np.timedelta64(5, "s")) != digest(5)
    assert digest(np.timedelta64(5, "s")) != digest(5.0)
    assert digest(np.timedelta64(5)) != digest(5)


# --- years and months ---


def test_years_digest_as_twelve_months():
    assert digest(np.timedelta64(1, "Y")) == digest(np.timedelta64(12, "M"))
    assert digest(np.timedelta64(2, "3Y")) == digest(np.timedelta64(6, "12M"))
    assert digest(np.timedelta64(-1, "Y")) == digest(np.timedelta64(-12, "M"))


@given(
    st.sampled_from(["Y", "M"]),
    st.sampled_from(MULTIPLIERS),
    counts,
    st.sampled_from(["Y", "M"]),
    st.sampled_from(MULTIPLIERS),
    counts,
)
def test_calendar_durations_digest_equal_exactly_when_months_equal(u1, m1, c1, u2, m2, c2):
    months = {"Y": 12, "M": 1}
    a, b = np.timedelta64(c1, f"{m1}{u1}"), np.timedelta64(c2, f"{m2}{u2}")
    assert (digest(a) == digest(b)) == (c1 * m1 * months[u1] == c2 * m2 * months[u2])


@pytest.mark.parametrize("unit", ["Y", "M"])
@pytest.mark.parametrize("count", [0, 1, 12, 30])
def test_calendar_durations_never_meet_fixed_ones(unit, count):
    # numpy refuses to compare them, so no digest equality is owed.
    with pytest.raises(TypeError):
        bool(np.timedelta64(count, unit) == np.timedelta64(count, "D"))
    calendar = digest(np.timedelta64(count, unit))
    for fixed_unit in SECONDS:
        assert calendar != digest(np.timedelta64(count, fixed_unit))
    assert calendar != digest(datetime.timedelta(days=count))


# --- the generic unit ---


def test_generic_unit_digests_as_its_own_kind():
    # numpy calls np.timedelta64(5) equal to 5 of any unit, which is not
    # transitive (5 s != 5 ms), so it meets none of them.
    generic = np.timedelta64(5)
    assert generic == np.timedelta64(5, "s") and generic == np.timedelta64(5, "ms")
    others = [np.timedelta64(5, unit) for unit in [*SECONDS, "Y", "M"]]
    others += [datetime.timedelta(seconds=5), 5]
    assert digest(generic) not in {digest(o) for o in others}
    assert digest(generic) == digest(np.timedelta64(5))
    assert digest(generic) != digest(np.timedelta64(6))
    assert digest(np.timedelta64(0)) != digest(np.timedelta64(0, "s"))


# --- NaT ---


@pytest.mark.parametrize("unit", [*SECONDS, "Y", "M", "10ms", "generic"])
def test_nat_digests_alike_in_every_unit(unit):
    nat = np.timedelta64("NaT") if unit == "generic" else np.timedelta64("NaT", unit)
    assert digest(nat) == digest(np.timedelta64("NaT", "ns"))
    # int64's minimum is how numpy stores NaT.
    if unit != "generic":
        assert digest(np.timedelta64(NAT, unit)) == digest(nat)
    assert digest(nat) != digest(np.timedelta64(0, "ns"))
    assert digest(nat) != digest(np.timedelta64(-INT64_MAX, "ns"))


def test_pandas_nat_keeps_its_datetime_digest():
    # pd.NaT is not a Timedelta: it subclasses datetime.datetime and stands
    # for missing datetimes too, so the datetime arm still digests it, and
    # apart from np.timedelta64's NaT.
    assert pd.Timedelta("NaT") is pd.NaT
    assert not isinstance(pd.NaT, datetime.timedelta)
    expected = new_hash(b"NaTType")
    expected.update(b"NaT")
    assert digest(pd.NaT) == expected.hexdigest()
    assert digest(pd.NaT) != digest(np.timedelta64("NaT", "ns"))


# --- inside other values ---


def test_durations_inside_containers():
    assert digest([np.timedelta64(1, "D")]) == digest([datetime.timedelta(days=1)])
    assert digest({"t": pd.Timedelta("1h")}) == digest({"t": np.timedelta64(60, "m")})


def test_object_column_of_durations():
    a = pd.Series([datetime.timedelta(seconds=1), np.timedelta64(2, "s")], dtype=object)
    b = pd.Series([np.timedelta64(1000, "ms"), pd.Timedelta("2s")], dtype=object)
    assert digest(a) == digest(b)


def test_timedelta_subclass_digests_as_its_duration():
    class Span(datetime.timedelta):
        pass

    assert digest(Span(hours=1)) == digest(datetime.timedelta(hours=1))


# --- timezones ---


def test_timezone_digests_its_offset_as_a_duration():
    offset = datetime.timedelta(hours=5, microseconds=1)
    expected = new_hash(b"timezone")
    expected.update(digest(offset).encode())
    assert digest(datetime.timezone(offset)) == expected.hexdigest()
    assert digest(datetime.timezone(offset)) == digest(
        datetime.timezone(datetime.timedelta(minutes=300, microseconds=1), "X")
    )
