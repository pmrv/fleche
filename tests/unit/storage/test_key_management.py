import inspect
from fleche.storage import (
    KeyManagement,
    StorageBackend,
    ValueStorage,
    CallStorage,
)
from fleche.storage.sql import Sql, SqlBackend


def test_key_management_is_base_of_storage_backend():
    assert issubclass(StorageBackend, KeyManagement)


def test_key_management_is_base_of_value_storage():
    assert issubclass(ValueStorage, KeyManagement)


def test_key_management_is_base_of_call_storage():
    assert issubclass(CallStorage, KeyManagement)


def test_sql_backend_is_key_management():
    assert issubclass(SqlBackend, KeyManagement)


def test_sql_backend_is_not_storage_backend():
    """SqlBackend should NOT inherit StorageBackend — that's the LSP fix."""
    assert not issubclass(SqlBackend, StorageBackend)


def test_sql_is_call_storage():
    assert issubclass(Sql, CallStorage)


def test_sql_is_not_storage_backend():
    """Sql should NOT inherit StorageBackend — it can only store Calls."""
    assert not issubclass(Sql, StorageBackend)


def test_sql_is_key_management():
    assert issubclass(Sql, KeyManagement)


def test_sql_query_uses_sqlbackend_implementation(tmp_path):
    """SqlBackend.query (SQL-optimized) must NOT be shadowed by CallMixin.query."""
    from fleche.storage.sql import SqlBackend
    sql = Sql(str(tmp_path / "test.db"))
    # SqlBackend.query is in the MRO before any generic Python-iteration query
    mro_names = [cls.__name__ for cls in type(sql).__mro__]
    sql_backend_idx = mro_names.index("SqlBackend")
    call_mixin_idx = mro_names.index("CallMixin") if "CallMixin" in mro_names else float("inf")
    assert sql_backend_idx < call_mixin_idx, (
        "SqlBackend must appear before CallMixin in Sql's MRO so its "
        "SQL-optimized query() is used"
    )


def test_call_storage_has_transform():
    """transform() should be a concrete method on CallStorage, not only on CallMixin."""
    assert callable(getattr(CallStorage, "transform", None))
    assert not getattr(CallStorage.transform, "__isabstractmethod__", False)
