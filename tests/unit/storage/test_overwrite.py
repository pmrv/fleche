import pytest
from fleche.storage import Memory, Sql, FileStorage
from fleche.call import Call
from fleche.digest import Digest
import tempfile
from pathlib import Path

def create_dummy_call(name, result):
    return Call(
        name=name,
        arguments={"x": 1},
        metadata={},
        module="test_module",
        version=1,
        code_digest="abc" * 16, # 64 chars
        result=Digest(result)
    )

@pytest.fixture
def memory_storage():
    return Memory({})

@pytest.fixture
def sql_storage():
    return Sql("sqlite:///:memory:")

@pytest.fixture
def file_storage():
    from fleche.storage import PickleFile
    with tempfile.TemporaryDirectory() as tmpdir:
        yield PickleFile.with_pickle(Path(tmpdir))

@pytest.mark.parametrize("storage_fixture", ["memory_storage", "sql_storage", "file_storage"])
def test_call_storage_overwrite(request, storage_fixture):
    storage = request.getfixturevalue(storage_fixture)

    from fleche.storage import CallStorage, CallStorageAdapter
    call_storage = storage if isinstance(storage, CallStorage) else CallStorageAdapter(storage)

    call1 = create_dummy_call("my_func", "1" * 64)
    key1 = call_storage.save(call1)

    assert call_storage.load(key1).result == "1" * 64

    # Save a call with same lookup key (name, arguments, module, version, code_digest) but different result
    call2 = create_dummy_call("my_func", "2" * 64)
    key2 = call_storage.save(call2)

    assert key1 == key2
    assert call_storage.load(key1).result == "2" * 64

    # We expect overwrite behavior at the storage level, which means only 1 entry should exist for the same lookup key.
    # Note: For Sql, call storage is separate from value storage.
    # For CallStorageAdapter, call is stored in value storage.
    assert len(list(call_storage.list())) == 1
