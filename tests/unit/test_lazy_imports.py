"""Optional heavy dependencies are imported on first use, not by ``import fleche``."""

import subprocess
import sys
from unittest.mock import patch

import pytest

from fleche import cache, fleche
from fleche.caches import Cache
from fleche.storage import CallMemory, ValueMemory


def _modules_after(code: str) -> set[str]:
    # A fresh interpreter: this one has long since imported everything.
    out = subprocess.run(
        [sys.executable, "-c", f"import sys; {code}; print('\\n'.join(sys.modules))"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return set(out.split())


@pytest.mark.parametrize("module", ["pandas", "sqlalchemy", "fleche.storage.sql"])
def test_import_fleche_does_not_import(module):
    assert module not in _modules_after("import fleche")


def test_sql_storage_from_config_imports_sql_on_demand():
    pytest.importorskip("sqlalchemy")
    code = (
        "from fleche.config import storage_from_config; "
        "s = storage_from_config({'type': 'sql', 'url': 'sqlite:///:memory:'}, 'call'); "
        "assert type(s).__name__ == 'Sql'"
    )
    assert "sqlalchemy" in _modules_after(code)


def test_sql_is_importable_from_storage():
    import fleche.storage
    from fleche.storage import Sql
    from fleche.storage.sql import Sql as SqlItself

    assert Sql is SqlItself
    assert "Sql" in dir(fleche.storage)
    with pytest.raises(AttributeError):
        fleche.storage.NoSuchBackend


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
        with pytest.raises(ImportError, match=r"table\(\) requires 'pandas'.*pip install pandas"):
            with pytest.warns(ImportWarning):
                c.table()


def test_table_with_pandas():
    pd = pytest.importorskip("pandas")
    assert isinstance(_cache_with_one_call().table(), pd.DataFrame)


def test_sql_constructor_resolves_from_a_registry_snapshot_taken_before_import():
    """A registry snapshot taken before fleche.storage.sql was imported holds
    no constructor for "sql"; restoring it after the import must still resolve."""
    pytest.importorskip("sqlalchemy")
    from fleche.storage import base
    from fleche.storage.sql import Sql

    unimported = ("fleche.storage.sql.Sql", None)
    with patch.dict(base._STORAGE, {("sql", "call"): unimported}):
        assert base.get_storage_constructor("sql", "call") is Sql


def test_the_sql_slot_is_reserved():
    """No other class may register as "sql", even before fleche.storage.sql is imported."""
    from fleche.storage import register_storage

    class MySql:
        pass

    with pytest.raises(ValueError, match="already registered to fleche.storage.sql.Sql"):
        register_storage("sql", kind="call")(MySql)


def test_sql_module_is_an_attribute_of_fleche_storage():
    code = "import fleche; fleche.storage.sql.Sql"
    assert "fleche.storage.sql" in _modules_after(code)
