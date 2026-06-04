"""Regression test for issue #218: Sql._save() race condition under concurrent access."""

from fleche.call import Call
from fleche.storage.sql import Sql

from tests.fixtures import run_workers


def test_sql_concurrent_save_no_integrity_error(tmp_path):
    """Multiple threads saving calls with overlapping keys must not raise IntegrityError.

    Threads save calls whose lookup keys collide (only 3 distinct inputs) so the
    check-evict-insert path in save() is exercised under genuine data races.
    """
    sql = Sql(str(tmp_path / "cache.db"))

    def save_call(worker):
        call = Call(name="compute", arguments={"x": worker % 3}, result=None)
        sql.save(call)

    errors = run_workers(save_call, 24)

    assert not errors, f"Concurrent saves raised errors: {errors}"
    stored_keys = list(sql.list())
    assert len(stored_keys) == 3, f"Expected 3 unique keys, got {len(stored_keys)}"
