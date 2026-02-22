import pytest

from fleche.storage.sql import Sql
from fleche.call import Call
from fleche.digest import Digest


def make_call():
    return Call(
        name="f",
        arguments={"a": "a" * 64, "b": "b" * 64, "x": "c" * 64},
        metadata={
            "tags": {"project": "alpha", "phase": "train"},
            "runtime": {"walltime": 1.23},
        },
        module=None,
        version=1,
        result="d" * 64,
    )


def test_sql_save_returns_digest(tmp_path):
    store = Sql(str(tmp_path / "calls.db"))
    key = store.save(make_call())
    assert isinstance(key, Digest)


def test_sql_list_returns_digests(tmp_path):
    store = Sql(str(tmp_path / "calls.db"))
    k1 = store.save(make_call())
    k2 = store.save(make_call())
    keys = list(store.list())
    assert all(isinstance(k, Digest) for k in keys)
    assert set(keys) >= {k1, k2}


def test_sql_expand_returns_digest(tmp_path):
    store = Sql(str(tmp_path / "calls.db"))
    key = store.save(make_call())
    prefix = str(key)[:8]
    expanded = store.expand(prefix)
    assert isinstance(expanded, Digest)
    assert expanded == key


def test_sql_find_by_metadata_returns_digests(tmp_path):
    store = Sql(str(tmp_path / "calls.db"))
    c1 = make_call()
    c2 = make_call()
    c1.name = "g"
    # Slightly vary metadata so queries can differentiate
    c2.metadata["tags"]["project"] = "beta"
    k1 = store.save(c1)
    k2 = store.save(c2)

    # Use query(template) for metadata filtering
    lc1 = store.load(k1)
    lc2 = store.load(k2)
    k1_loaded = lc1.to_lookup_key()
    k2_loaded = lc2.to_lookup_key()

    tpl = Call(name=None, arguments=None, metadata={"tags": {"project": "alpha"}}, module=None, version=None, result=None)
    got = {c.to_lookup_key() for c in store.query(tpl)}
    assert k1_loaded in got and k2_loaded not in got


def test_sql_load_returns_digest_fields(tmp_path):
    store = Sql(str(tmp_path / "calls.db"))
    key = store.save(make_call())
    loaded = store.load(key)

    assert all(isinstance(v, Digest) for v in loaded.arguments.values())
    assert isinstance(loaded.result, Digest)
