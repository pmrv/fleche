import pytest

from fleche.storage.sql import Sql
from fleche.call import Call
from fleche.digest import Digest


def make_call():
    return Call(
        name="f",
        args=("a" * 64, "b" * 64),
        kwargs={"x": "c" * 64},
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
    # Slightly vary metadata so queries can differentiate
    c2.metadata["tags"]["project"] = "beta"
    k1 = store.save(c1)
    k2 = store.save(c2)

    keys_alpha = store.find_by_metadata(name="tags", project="alpha")
    assert all(isinstance(k, Digest) for k in keys_alpha)
    assert k1 in set(keys_alpha) and k2 not in set(keys_alpha)


def test_sql_load_returns_digest_fields(tmp_path):
    store = Sql(str(tmp_path / "calls.db"))
    key = store.save(make_call())
    loaded = store.load(key)

    assert all(isinstance(a, Digest) for a in loaded.args)
    assert all(isinstance(v, Digest) for v in loaded.kwargs.values())
    assert isinstance(loaded.result, Digest)
