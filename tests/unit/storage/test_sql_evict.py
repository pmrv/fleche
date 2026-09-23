"""Eviction tests for the SQL call backend.

``Sql._evict`` deliberately bypasses the ORM: instead of loading the
``CallModel`` and letting SQLAlchemy's ``delete-orphan`` cascade walk the
relationship in Python, it issues a bare ``DELETE ... WHERE key = ...`` and
relies on the database to clean up the dependent ``arguments`` and
``metadata`` rows through their ``ON DELETE CASCADE`` foreign keys (SQLite
needs ``PRAGMA foreign_keys=ON``, which the backend sets on every connect).

That makes the row cleanup a property of the schema and the connection
setup rather than of the delete statement, so it is asserted here against
the tables directly -- ``load``/``contains`` would still report the call as
gone even if the child rows were orphaned.
"""

import pytest
from sqlalchemy import func, select

from fleche.call import Call
from fleche.storage.sql import ArgumentModel, CallModel, MetaModel, Sql


@pytest.fixture
def store():
    return Sql()  # in-memory sqlite


def make_call(name="f", arg="a", meta_name="tags"):
    return Call(
        name=name,
        arguments={arg: "a" * 64, "b": "b" * 64},
        metadata={meta_name: {"project": "alpha"}},
        module="m",
        version=1,
        result="r" * 64,
    )


def count_rows(store: Sql, model, key) -> int:
    with store._session_context():
        return store._local.session.execute(
            select(func.count())
            .select_from(model)
            .where(model.call_key == str(key))
        ).scalar_one()


def test_evict_removes_the_call(store):
    """The evicted key is gone from the calls table."""
    key = store.save(make_call())

    store.evict(key)

    assert not store.contains(key)
    with pytest.raises(KeyError):
        store.load(key)


def test_evict_cascades_to_argument_rows(store):
    """The ``arguments`` rows go with the call rather than being orphaned."""
    key = store.save(make_call())
    assert count_rows(store, ArgumentModel, key) == 2

    store.evict(key)

    assert count_rows(store, ArgumentModel, key) == 0


def test_evict_cascades_to_metadata_rows(store):
    """The ``metadata`` rows go with the call too.

    Unlike ``arguments``, ``metadata`` has no ORM relationship on
    ``CallModel``, so nothing but the foreign key's ``ON DELETE CASCADE``
    stands between an eviction and a leaked row.
    """
    key = store.save(make_call())
    assert count_rows(store, MetaModel, key) == 1

    store.evict(key)

    assert count_rows(store, MetaModel, key) == 0


def test_evict_leaves_other_calls_untouched(store):
    """Eviction is scoped to its key: the sibling call survives intact."""
    doomed = store.save(make_call(name="doomed"))
    survivor = store.save(make_call(name="survivor"))

    store.evict(doomed)

    assert store.load(survivor) == make_call(name="survivor")
    assert count_rows(store, ArgumentModel, survivor) == 2
    assert count_rows(store, MetaModel, survivor) == 1


def test_evict_of_absent_key_is_a_noop(store):
    """Deleting nothing still commits cleanly instead of raising.

    ``CallMixin.save`` evicts before writing, so a backend that objected to
    a zero-row delete would break the very first save into an empty table.
    """
    store.evict("0" * 64)

    with store._session_context():
        assert (
            store._local.session.execute(
                select(func.count()).select_from(CallModel)
            ).scalar_one()
            == 0
        )
