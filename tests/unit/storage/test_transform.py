import pytest
from dataclasses import replace
from fleche.storage import Memory, Sql, PickleFile, CloudpickleFile, BagOfHoldingH5File
from fleche.call import Call
from fleche.digest import Digest

@pytest.fixture(params=["memory", "cloudpickle", "pickle", "h5", "sql"])
def storage(request, tmp_path):
    if request.param == "memory":
        return Memory({})
    elif request.param == "cloudpickle":
        return CloudpickleFile(tmp_path / "cloudpickle")
    elif request.param == "pickle":
        return PickleFile(tmp_path / "pickle")
    elif request.param == "h5":
        return BagOfHoldingH5File(tmp_path / "h5")
    elif request.param == "sql":
        return Sql(tmp_path / "calls.db")

def test_transform_basic(storage):
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
    assert str(loaded.result) == "r" * 64

def test_transform_key_change(storage):
    c1 = Call(name="f1", arguments={"a": Digest("a" * 64)}, metadata={"m": 1}, result=Digest("r" * 64))
    k1 = c1.to_lookup_key()
    storage.save(c1, key=k1)

    # Transform: change argument, change key
    def change_arg(call):
        return replace(call, arguments={"a": Digest("b" * 64)})

    storage.transform(change_arg)

    all_keys = list(storage.list())
    assert len(all_keys) == 1
    assert k1 not in all_keys

    new_c = replace(c1, arguments={"a": Digest("b" * 64)})
    new_k = new_c.to_lookup_key()
    assert new_k in all_keys
    loaded = storage.load(new_k)
    assert str(loaded.arguments["a"]) == "b" * 64

def test_redigest(storage):
    c1 = Call(name="f1", arguments={"a": Digest("a" * 64)}, metadata={"m": 1}, result=Digest("r" * 64))
    # Save with a WRONG key
    wrong_key = "f" * 64
    storage.save(c1, key=wrong_key)

    assert wrong_key in list(storage.list())

    storage.redigest()

    all_keys = list(storage.list())
    assert len(all_keys) == 1
    assert wrong_key not in all_keys
    assert c1.to_lookup_key() in all_keys
