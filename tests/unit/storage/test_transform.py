import pytest
from unittest.mock import patch
from dataclasses import replace
from fleche.storage import Memory, Sql, PickleFile, BagOfHoldingH5File, CallStorageAdapter
from fleche.call import Call
from fleche.digest import Digest

@pytest.fixture(params=["memory", "cloudpickle", "pickle", "h5", "sql"])
def storage(request, tmp_path):
    if request.param == "memory":
        return CallStorageAdapter(Memory({}))
    elif request.param == "cloudpickle":
        return CallStorageAdapter(PickleFile.from_cloudpickle(tmp_path / "cloudpickle"))
    elif request.param == "pickle":
        return CallStorageAdapter(PickleFile.from_pickle(tmp_path / "pickle"))
    elif request.param == "h5":
        return CallStorageAdapter(BagOfHoldingH5File(tmp_path / "h5"))
    elif request.param == "sql":
        return Sql(tmp_path / "calls.db")

def test_transform_basic(storage):
    c1 = Call(name="f1", arguments={"a": Digest("a" * 64)}, metadata={"table": {"m": 1}}, result=Digest("r" * 64))
    storage.save(c1)

    # Transform: update metadata, keep same key
    def update_metadata(call):
        return replace(call, metadata={"table": {"m": 2}})

    storage.transform(update_metadata)

    assert len(list(storage.list())) == 1
    k1 = c1.to_lookup_key()
    loaded = storage.load(k1)
    assert loaded.metadata == {"table": {"m": 2}}
    assert str(loaded.result) == "r" * 64

def test_transform_key_change(storage):
    c1 = Call(name="f1", arguments={"a": Digest("a" * 64)}, metadata={}, result=Digest("r" * 64))
    storage.save(c1)

    # Transform: change argument, change key
    def change_arg(call):
        return replace(call, arguments={"a": Digest("b" * 64)})

    storage.transform(change_arg)

    all_keys = list(storage.list())
    assert len(all_keys) == 1
    assert c1.to_lookup_key() not in all_keys

    new_c = replace(c1, arguments={"a": Digest("b" * 64)})
    new_k = new_c.to_lookup_key()
    assert new_k in all_keys
    loaded = storage.load(new_k)
    assert str(loaded.arguments["a"]) == "b" * 64
