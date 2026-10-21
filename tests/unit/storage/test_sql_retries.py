"""Retries in the Sql backend for collisions between concurrent processes.

Both races need a shared database server and several processes to show up
for real (``tests/integration/test_dbserver.py`` exercises them); here the
failures are injected so the retry logic is covered on plain sqlite.
"""

import pytest
from sqlalchemy.exc import OperationalError

from fleche.call import Call
from fleche.storage import sql as sql_module
from fleche.storage.sql import Sql


class _DriverError(Exception):
    pass


def _operational_error(*args, pgcode=None):
    orig = _DriverError(*args)
    orig.pgcode = pgcode
    return OperationalError("INSERT ...", {}, orig)


def _fail_first(monkeypatch, target, name, errors):
    """Make ``target.name`` raise each of *errors* once before succeeding."""
    real = getattr(target, name)
    pending = list(errors)
    calls = []

    def flaky(*args, **kwargs):
        calls.append(None)
        if pending:
            raise pending.pop(0)
        return real(*args, **kwargs)

    monkeypatch.setattr(target, name, flaky)
    return calls


def test_create_schema_retries_concurrent_create_table(monkeypatch):
    """Losing the CREATE TABLE race to another process is retried."""
    calls = _fail_first(
        monkeypatch,
        sql_module.Base.metadata,
        "create_all",
        [_operational_error(1050, "Table 'arguments' already exists")],
    )
    Sql()
    assert len(calls) == 2


@pytest.mark.parametrize(
    "error",
    [
        _operational_error(1213, "Deadlock found when trying to get lock"),
        _operational_error("deadlock detected", pgcode="40P01"),
    ],
    ids=["mariadb", "postgres"],
)
def test_save_retries_deadlock(monkeypatch, error):
    sql = Sql()
    calls = _fail_first(monkeypatch, Sql, "_persist_call", [error, error])
    call = Call(name="f", arguments={"x": 1}, result=None)
    key = sql.save(call)
    assert len(calls) == 3
    assert list(sql.list()) == [key]


def test_save_does_not_retry_other_errors(monkeypatch):
    sql = Sql()
    calls = _fail_first(
        monkeypatch, Sql, "_persist_call", [_operational_error(2006, "server has gone away")]
    )
    with pytest.raises(OperationalError):
        sql.save(Call(name="f", arguments={"x": 1}, result=None))
    assert len(calls) == 1


def test_save_gives_up_after_repeated_deadlocks(monkeypatch):
    sql = Sql()
    deadlock = _operational_error(1213, "Deadlock found when trying to get lock")
    calls = _fail_first(
        monkeypatch, Sql, "_persist_call", [deadlock] * sql_module._DEADLOCK_ATTEMPTS
    )
    with pytest.raises(OperationalError):
        sql.save(Call(name="f", arguments={"x": 1}, result=None))
    assert len(calls) == sql_module._DEADLOCK_ATTEMPTS
