import pytest
from fleche.call import Call
from fleche.digest import Digest

def create_dummy_call(name, result, metadata=None):
    return Call(
        name=name,
        arguments={"x": 1},
        metadata=metadata or {},
        module="test_module",
        version=1,
        code_digest="abc" * 16, # 64 chars
        result=Digest(result)
    )

def test_call_storage_overwrite(call_storage):
    call1 = create_dummy_call("my_func", "1" * 64)
    key1 = call_storage.save(call1)

    assert call_storage.load(key1).result == "1" * 64

    # Save a call with same lookup key (name, arguments, module, version, code_digest) but different result
    call2 = create_dummy_call("my_func", "2" * 64)
    key2 = call_storage.save(call2)

    assert key1 == key2
    assert call_storage.load(key1).result == "2" * 64

    # We expect overwrite behavior at the storage level, which means only 1 entry should exist for the same lookup key.
    assert len(list(call_storage.list())) == 1

def test_call_storage_overwrite_differing_metadata(call_storage):
    call1 = create_dummy_call("my_func", "1" * 64, metadata={"tags": {"a": 1}})
    key1 = call_storage.save(call1)

    assert call_storage.load(key1).metadata == {"tags": {"a": 1}}

    # Save a call with same lookup key but different metadata
    call2 = create_dummy_call("my_func", "1" * 64, metadata={"tags": {"a": 2}})
    key2 = call_storage.save(call2)

    # Metadata is NOT part of the lookup key
    assert key1 == key2
    assert call_storage.load(key1).metadata == {"tags": {"a": 2}}
    assert len(list(call_storage.list())) == 1
