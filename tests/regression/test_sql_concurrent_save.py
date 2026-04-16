"""Regression test for issue #218: Sql._save() race condition under concurrent access."""

import concurrent.futures

from fleche.call import Call
from fleche.storage.sql import Sql


def test_sql_concurrent_save_no_integrity_error(tmp_path):
    """Multiple threads saving calls with overlapping keys must not raise IntegrityError.

    Threads save calls whose lookup keys collide (only 3 distinct inputs) so the
    check-evict-insert path in save() is exercised under genuine data races.
    """
    sql = Sql(str(tmp_path / "cache.db"))

    errors = []

    def save_call(x):
        try:
            call = Call(name="compute", arguments={"x": x}, result=None)
            sql.save(call)
        except Exception as exc:
            errors.append(exc)

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(save_call, i % 3) for i in range(24)]
        for f in futures:
            f.result()

    assert not errors, f"Concurrent saves raised errors: {errors}"
    stored_keys = list(sql.list())
    assert len(stored_keys) == 3, f"Expected 3 unique keys, got {len(stored_keys)}"
