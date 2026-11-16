"""The numpy and pandas digests ship as sister packages, fleche-numpy and fleche-pandas.

fleche must refuse their types when the packages are missing, rather than fall
through to a built-in arm that digests them silently and wrongly, and moving the
digests out of fleche must not have changed a single key.
"""

import datetime
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest
from ase import Atoms
from ase.calculators.lj import LennardJones

import fleche_numpy
import fleche_pandas
import fleche.digest as fd
from fleche.digest import Hook, Indigestible, add_hook, digest, load_entry_points


@pytest.fixture
def without_sister_packages():
    """Digest as if neither sister package were installed."""
    saved = fd._HOOKS, fd._EP_HOOKS
    fd._set_hooks((), ())
    with patch("importlib.metadata.entry_points", return_value=[]):
        yield
    fd._set_hooks(*saved)


@pytest.fixture
def clean_hooks():
    yield
    fd._set_hooks(manual=())
    load_entry_points()


def test_sister_packages_register_their_hooks():
    load_entry_points()
    registered = {h.type for h in fd._EP_HOOKS}
    assert {t for t, _ in fleche_numpy.digest_hooks} <= registered
    assert {t for t, _ in fleche_pandas.digest_hooks} <= registered


# Digests computed by fleche 0.23.1, before the numpy and pandas arms moved out.
# Restricted to values whose digest does not depend on the numpy or pandas
# version (pandas 3 infers a str dtype where pandas 2 infers object).
PRE_SPLIT_DIGESTS = [
    (np.arange(10, dtype=np.int64), "5c12f407a4df527d92d428426e8f0eff5f0d0c718528a299a9c01e94b81c4142"),
    (
        np.array([(1, 2.0), (3, 4.0)], dtype=[("a", "i4"), ("b", "f8")]),
        "5277620ec51aad663d4e3c1332adcb1f8a220aa5c5e950b087ac2c8da841db73",
    ),
    (np.bool_(True), "45c66d1f3a4d21aff0b1af98417af5ee138eb8391be9330f83642bb9c4c70eca"),
    (np.timedelta64(5000, "ms"), "0f2878f5b9a1cf0d9915e91ab8d442c2e5b971048fc399d3da690babbdabceff"),
    (pd.Index([1, 2, 3], name="i"), "55c5787aca2af77b2a1ac90fdcddc2d2005fbe4560d6d1c4b6c5995018b6dc68"),
    (pd.RangeIndex(5), "5a7f23254dedb5afd9421f661d1001f7899d459c2290b2e1939327374cf25aac"),
    (pd.Timedelta(seconds=3), "9f8ba35e5ce4d6587a15658187ca891620e7b091d0a284aca33219330bb892ce"),
    (pd.NA, "a9bde9b9df5bf82371fc7682b793aa49cfcf3b689c81fe174bf348e160183133"),
]


@pytest.mark.parametrize("value, expected", PRE_SPLIT_DIGESTS, ids=lambda v: type(v).__name__)
def test_digests_are_unchanged_by_the_split(value, expected):
    assert digest(value) == expected


@pytest.mark.parametrize(
    "value, package",
    [
        (np.arange(3), "fleche-numpy"),
        (np.ma.masked_array([1, 2]), "fleche-numpy"),  # an ndarray subclass
        (np.array(5), "fleche-numpy"),  # 0-d arrays are not even iterable
        (np.bool_(False), "fleche-numpy"),
        # numpy registers timedelta64 as numbers.Integral: the Number arm
        # would digest it as its bare count.
        (np.timedelta64(5, "s"), "fleche-numpy"),
        # The Iterable arm would digest a frame by its column names alone.
        (pd.DataFrame({"a": [1, 2]}), "fleche-pandas"),
        (pd.Series([1, 2]), "fleche-pandas"),
        (pd.MultiIndex.from_tuples([(1, 2)]), "fleche-pandas"),
        # A datetime.timedelta subclass; it must not digest like one.
        (pd.Timedelta(seconds=1), "fleche-pandas"),
        (pd.NA, "fleche-pandas"),
        # Iterable, of Atom objects.
        (Atoms("H2", positions=[(0, 0, 0), (0, 0, 0.74)]), "fleche-ase"),
        (LennardJones(), "fleche-ase"),  # a Calculator subclass
    ],
    ids=lambda v: v if isinstance(v, str) else type(v).__name__,
)
def test_missing_sister_package_is_indigestible(without_sister_packages, value, package):
    with pytest.raises(Indigestible):
        digest(value)
    assert package in fd._install_hint(value)


def test_missing_sister_package_inside_a_container(without_sister_packages):
    with pytest.raises(Indigestible):
        digest({"x": [1, np.arange(3)]})


@pytest.mark.parametrize(
    "value",
    [np.float64(1.5), np.int32(3), np.complex64(1j), np.str_("a"), pd.Timestamp("2024-01-01"), pd.NaT],
    ids=lambda v: type(v).__name__,
)
def test_values_fleche_digests_itself_need_no_sister_package(value):
    """numpy scalars are numbers (or strings), pandas timestamps datetimes."""
    expected = digest(value)
    saved = fd._HOOKS, fd._EP_HOOKS
    fd._set_hooks((), ())
    try:
        with patch("importlib.metadata.entry_points", return_value=[]):
            assert digest(value) == expected
    finally:
        fd._set_hooks(*saved)


def test_pandas_timedelta_still_digests_apart_from_datetime_timedelta():
    assert digest(pd.Timedelta(seconds=3)) != digest(datetime.timedelta(seconds=3))


def test_add_hook_overrides_a_sister_package(clean_hooks):
    add_hook(Hook(np.ndarray, lambda a: digest(("mine", a.tolist()))))
    assert digest(np.arange(3)) == digest(("mine", [0, 1, 2]))


class _OwnDigestArray(np.ndarray):
    def __digest__(self):
        return digest(("own", self.tolist()))


class _OwnDigestFrame(pd.DataFrame):
    def __digest__(self):
        return digest(("own", self.to_dict()))


@pytest.mark.parametrize(
    "make",
    [lambda: np.arange(3).view(_OwnDigestArray), lambda: _OwnDigestFrame({"a": [1, 2]})],
    ids=["ndarray", "DataFrame"],
)
def test_own_digest_wins_over_sister_hooks_whenever_they_load(make):
    """``__digest__`` beat the built-in numpy/pandas arms; it must beat their
    hooks too, and before and after the hooks load alike."""
    value = make()
    saved = fd._EP_HOOKS
    fd._set_hooks(entry_points=())
    try:
        before = digest(value)  # entry points not loaded
    finally:
        fd._set_hooks(entry_points=saved)
    load_entry_points()
    assert digest(value) == before == value.__digest__()


def test_missing_sister_package_names_it_when_caching_is_skipped(without_sister_packages, caplog):
    from fleche import cache, fleche
    from fleche.caches import Cache
    from fleche.storage import CallMemory, ValueMemory

    @fleche()
    def total(a):
        return int(a.sum())

    with cache(Cache(ValueMemory({}), CallMemory({}))), caplog.at_level("WARNING"):
        assert total(np.arange(3)) == 3
    assert "install fleche-numpy" in caplog.text


def test_entry_point_hooks_for_a_subclass_beat_their_base_whatever_the_order(clean_hooks):
    from unittest.mock import MagicMock

    class Sub(np.ndarray):
        pass

    plugin = MagicMock()
    plugin.load.return_value = [(Sub, lambda a: digest(("sub", a.tolist())))]
    numpy_ep = MagicMock()
    numpy_ep.load.return_value = fleche_numpy.digest_hooks
    value = np.arange(2).view(Sub)
    for order in ([numpy_ep, plugin], [plugin, numpy_ep]):
        with patch("importlib.metadata.entry_points", return_value=order):
            load_entry_points()
        assert digest(value) == digest(("sub", [0, 1]))


def test_missing_sister_package_named_when_a_capture_is_indigestible(without_sister_packages, caplog):
    from fleche.call import _code_digest

    weights = np.arange(3)

    def scaled(x):
        return x * weights

    with caplog.at_level("WARNING"):
        _code_digest(scaled)
    assert "install fleche-numpy" in caplog.text
