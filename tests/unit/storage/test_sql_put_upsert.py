"""Regression tests for the optimistic-insert path in Sql.put().

Sql.put() no longer issues a SELECT-by-PK before every write; it optimistically
attempts the INSERT and falls back to the collision path only on IntegrityError.
These tests verify that the visible semantics are preserved.
"""

from fleche.storage.sql import Sql
from fleche.call import Call
from fleche.digest import Digest


def _make_call(name="f", arg_val="a" * 64, metadata=None, result="r" * 64):
    return Call(
        name=name,
        arguments={"x": arg_val},
        metadata=metadata or {},
        result=Digest(result),
    )


def test_put_new_key_is_stored(tmp_path):
    """Fresh insert stores the call and returns its key."""
    store = Sql(str(tmp_path / "cache.db"))
    c = _make_call()
    key = store.save(c)
    assert isinstance(key, Digest)
    assert store.load(key).name == "f"


def test_put_idempotent_same_call(tmp_path):
    """Saving the same call twice is a no-op: one row, same key."""
    store = Sql(str(tmp_path / "cache.db"))
    c = _make_call()
    k1 = store.save(c)
    k2 = store.save(c)
    assert k1 == k2
    assert len(list(store.list())) == 1


def test_put_collision_replaces_content(tmp_path):
    """A call with the same key but different metadata replaces the stored record."""
    store = Sql(str(tmp_path / "cache.db"))
    c1 = _make_call(metadata={"tags": {"v": 1}})
    c2 = _make_call(metadata={"tags": {"v": 2}})
    k1 = store.save(c1)
    k2 = store.save(c2)
    assert k1 == k2
    loaded = store.load(k1)
    assert loaded.metadata == {"tags": {"v": 2}}
    assert len(list(store.list())) == 1
