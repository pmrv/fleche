"""Smoke tests touching each optional dependency.

This is a deliberately tiny, fast test set whose sole purpose is to confirm
that every *optional* dependency is importable **and** minimally functional
end-to-end — i.e. that a value can make a full round-trip through the backend
(or code path) that the dependency powers.  It is intended as a pre-release
sanity check for the packaged (e.g. conda) distribution, where you install the
package together with all of its extras and run::

    pytest -m smoke

Each test is marked ``smoke`` so the whole set can be selected with the marker.
Each dependency is loaded with :func:`pytest.importorskip`, so the set runs
against whatever happens to be installed and *skips* (rather than errors) on a
genuinely absent dependency — when run in an environment with all extras
present, every test should execute, and a dependency that is installed but
broken will fail loudly.
"""

import pytest

from fleche import fleche, cache
from fleche.caches import Cache
from fleche.storage import ValueMemory, CallMemory

pytestmark = pytest.mark.smoke


def _assert_roundtrip(c):
    """Run a decorated function twice through cache *c*; assert it round-trips.

    The function records every real execution in a list; a working cache means
    the second invocation is served from storage and the body does not run
    again, while still returning the correct value.
    """
    calls = []

    @fleche()
    def add(x, y):
        calls.append((x, y))
        return x + y

    with cache(c):
        assert add(2, 3) == 5  # miss -> computed + stored
        assert add(2, 3) == 5  # hit  -> loaded from backend

    assert calls == [(2, 3)], "second call should have been served from cache"


def test_cloudpickle(tmp_path):
    """cloudpickle-serialised file backend round-trips a value."""
    pytest.importorskip("cloudpickle")
    from fleche.storage import ValuePickleFile, CallPickleFile

    _assert_roundtrip(
        Cache(
            ValuePickleFile.with_cloudpickle(root=tmp_path / "values"),
            CallPickleFile.with_cloudpickle(root=tmp_path / "calls"),
        )
    )


def test_dill(tmp_path):
    """dill-serialised file backend round-trips a value."""
    pytest.importorskip("dill")
    from fleche.storage import ValuePickleFile, CallPickleFile

    _assert_roundtrip(
        Cache(
            ValuePickleFile.with_dill(root=tmp_path / "values"),
            CallPickleFile.with_dill(root=tmp_path / "calls"),
        )
    )


def test_sqlalchemy(tmp_path):
    """SQLAlchemy calls backend round-trips a call record."""
    pytest.importorskip("sqlalchemy")
    from fleche.storage import Sql

    # Sql stores call records only; values live in memory for this round-trip.
    _assert_roundtrip(
        Cache(ValueMemory({}), Sql(f"sqlite:///{tmp_path / 'calls.db'}"))
    )


def test_bagofholding(tmp_path):
    """bagofholding (HDF5) backend round-trips a value."""
    pytest.importorskip("bagofholding")
    from fleche.storage import ValueBagOfHoldingH5File, CallBagOfHoldingH5File

    _assert_roundtrip(
        Cache(
            ValueBagOfHoldingH5File(root=tmp_path / "values"),
            CallBagOfHoldingH5File(root=tmp_path / "calls"),
        )
    )


def test_attrs():
    """attrs instances are digestible and usable as cache-key arguments."""
    pytest.importorskip("attr")
    import attrs

    from fleche.digest import digest

    @attrs.define(frozen=True)
    class Point:
        x: int
        y: int

    # The attrs-class digest path must produce a stable key.
    assert digest(Point(1, 2)) == digest(Point(1, 2))

    calls = []

    @fleche()
    def norm(p):
        calls.append(p)
        return p.x + p.y

    with cache(Cache(ValueMemory({}), CallMemory({}))):
        assert norm(Point(1, 2)) == 3
        assert norm(Point(1, 2)) == 3

    assert calls == [Point(1, 2)], "attrs arg should hash to a cache hit"


def test_executorlib():
    """executorlib's executor accepts and runs a fleche-decorated function."""
    pytest.importorskip("executorlib")
    from executorlib import SingleNodeExecutor

    @fleche()
    def double(x):
        return x * 2

    with SingleNodeExecutor() as executor:
        assert executor.submit(double, 21).result() == 42
