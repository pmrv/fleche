
import pytest
from sqlalchemy import create_engine, text
from fleche.storage.sql import Sql
from pathlib import Path

def test_sqlite_foreign_keys_are_enabled(tmp_path):
    """Verify that foreign keys are enabled on the SQLite connection created by Sql."""
    db_path = tmp_path / "test_fk.db"
    sql_storage = Sql(str(db_path))

    # We need to access the underlying engine connection to check PRAGMA
    with sql_storage.engine.connect() as conn:
        result = conn.execute(text("PRAGMA foreign_keys")).scalar()
        assert result == 1, "Foreign keys should be enabled (PRAGMA foreign_keys=1)"

def test_sqlite_foreign_keys_explicit_url(tmp_path):
    """Verify foreign keys are enabled even when a full URL is provided."""
    db_path = tmp_path / "test_fk_explicit.db"
    url = f"sqlite:///{db_path}"
    sql_storage = Sql(url)

    with sql_storage.engine.connect() as conn:
        result = conn.execute(text("PRAGMA foreign_keys")).scalar()
        assert result == 1, "Foreign keys should be enabled for explicit URLs"

def test_sqlite_memory_foreign_keys():
    """Verify foreign keys are enabled for in-memory SQLite databases."""
    sql_storage = Sql("sqlite:///:memory:")

    with sql_storage.engine.connect() as conn:
        result = conn.execute(text("PRAGMA foreign_keys")).scalar()
        assert result == 1, "Foreign keys should be enabled for in-memory DBs"
