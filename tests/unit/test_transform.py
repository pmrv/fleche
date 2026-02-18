import pytest
from dataclasses import replace
from pathlib import Path
from fleche.storage import Memory, Sql, PickleFile
from fleche.call import Call
from fleche.digest import Digest

def test_transform_memory():
    storage = Memory({})
    # Use Digest for arguments to match how they are stored/loaded in some backends
    c1 = Call(name="f1", arguments={"a": Digest("a" * 64)}, metadata={"m": 1}, result=Digest("r" * 64))
    k1 = c1.to_lookup_key()
    storage.save(c1, key=k1)

    # Transform: update metadata, keep same key
    def update_metadata(call):
        return replace(call, metadata={"m": 2})

    storage.transform(update_metadata)

    assert len(list(storage.list())) == 1
    loaded = storage.load(k1)
    assert loaded.metadata == {"m": 2}
    assert loaded.result == "r" * 64

    # Transform: change argument, change key
    def change_arg(call):
        # Result and metadata are preserved by transform unless we change them here
        return replace(call, arguments={"a": Digest("b" * 64)})

    storage.transform(change_arg)

    all_keys = list(storage.list())
    assert len(all_keys) == 1
    assert k1 not in all_keys

    new_c = replace(c1, arguments={"a": Digest("b" * 64)}, metadata={"m": 2})
    new_k = new_c.to_lookup_key()
    assert new_k in all_keys
    loaded = storage.load(new_k)
    assert loaded.arguments == {"a": "b" * 64}
    assert loaded.metadata == {"m": 2}

def test_transform_sql(tmp_path):
    storage = Sql(str(tmp_path / "test.db"))
    c1 = Call(name="f1", arguments={"a": Digest("a" * 64)}, metadata={"tags": {"v": 1}}, result=Digest("r" * 64))
    k1 = c1.to_lookup_key()
    storage.save(c1, key=k1)

    def update_metadata(call):
        return replace(call, metadata={"tags": {"v": 2}})

    storage.transform(update_metadata)

    loaded = storage.load(k1)
    assert loaded.metadata == {"tags": {"v": 2}}
    assert loaded.result == "r" * 64

    # Test key change in SQL
    def change_name(call):
        return replace(call, name="f2")

    storage.transform(change_name)
    all_keys = list(storage.list())
    assert len(all_keys) == 1
    assert k1 not in all_keys

    new_c = replace(c1, name="f2", metadata={"tags": {"v": 2}})
    new_k = new_c.to_lookup_key()
    assert new_k in all_keys
    loaded = storage.load(new_k)
    assert loaded.name == "f2"

def test_transform_pickle(tmp_path):
    storage = PickleFile(tmp_path)
    c1 = Call(name="f1", arguments={"a": Digest("a" * 64)}, metadata={"m": 1}, result=Digest("r" * 64))
    k1 = c1.to_lookup_key()
    storage.save(c1, key=k1)

    def update_result(call):
        return replace(call, result=Digest("c" * 64))

    storage.transform(update_result)

    loaded = storage.load(k1)
    assert loaded.result == Digest("c" * 64)
    assert loaded.metadata == {"m": 1}
