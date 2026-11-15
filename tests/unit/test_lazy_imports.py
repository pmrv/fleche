"""Optional heavy dependencies are imported on first use, not by ``import fleche``."""

import subprocess
import sys
from unittest.mock import patch

import pytest

from fleche import cache, fleche
from fleche.caches import Cache
from fleche.storage import CallMemory, ValueMemory


def _modules_after_import_fleche() -> set[str]:
    # A fresh interpreter: this one has long since imported everything.
    out = subprocess.run(
        [sys.executable, "-c", "import sys, fleche; print('\\n'.join(sys.modules))"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return set(out.split())


def test_import_fleche_does_not_import_pandas():
    assert "pandas" not in _modules_after_import_fleche()


def _cache_with_one_call() -> Cache:
    c = Cache(ValueMemory({}), CallMemory({}))

    @fleche()
    def double(x):
        return 2 * x

    with cache(c):
        double(1)
    return c


def test_table_without_pandas_raises_import_error():
    c = _cache_with_one_call()
    with patch.dict(sys.modules, {"pandas": None}):
        with pytest.raises(ImportError, match=r"table\(\) requires 'pandas'"):
            with pytest.warns(ImportWarning):
                c.table()


def test_table_with_pandas():
    pd = pytest.importorskip("pandas")
    assert isinstance(_cache_with_one_call().table(), pd.DataFrame)
