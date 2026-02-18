import pytest
import tempfile
from pathlib import Path
from dataclasses import replace
from fleche.storage import Memory, Sql, PickleFile, CloudpickleFile, BagOfHoldingH5File
from fleche.call import Call
from fleche.digest import Digest

# Setup temporary directories for persistent storages
temp_calls_root = tempfile.TemporaryDirectory()
temp_calls_pickle = tempfile.TemporaryDirectory()
temp_calls_h5 = tempfile.TemporaryDirectory()
temp_calls_sql = tempfile.TemporaryDirectory()

call_storages = [
    Memory({}),
    CloudpickleFile(temp_calls_root.name),
    PickleFile(temp_calls_pickle.name),
    BagOfHoldingH5File(temp_calls_h5.name),
    Sql(Path(temp_calls_sql.name) / "calls.db"),
]

@pytest.mark.parametrize("storage", call_storages)
def test_transform_basic(storage):
    # Clear storage if it's persistent (Memory is fresh each time due to parametrize creating new instances if we define them in a list, but wait, call_storages is defined once)
    # Actually, for Memory({}) in a list, it's the same dict. Let's make sure it's fresh.
    if isinstance(storage, Memory):
        storage.storage.clear()
    else:
        for k in list(storage.list()):
            storage.evict(k)

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

@pytest.mark.parametrize("storage", call_storages)
def test_transform_key_change(storage):
    if isinstance(storage, Memory):
        storage.storage.clear()
    else:
        for k in list(storage.list()):
            storage.evict(k)

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

@pytest.mark.parametrize("storage", call_storages)
def test_redigest(storage):
    if isinstance(storage, Memory):
        storage.storage.clear()
    else:
        for k in list(storage.list()):
            storage.evict(k)

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
