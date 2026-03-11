import pytest
from unittest.mock import patch
from dataclasses import replace
from fleche.storage import (
    Memory,
    Sql,
    PickleFile,
    BagOfHoldingH5File,
    CallStorageAdapter,
)
from fleche.call import Call
from fleche.digest import Digest
from tests.fixtures import call_storage_adapter


def test_transform_basic(call_storage_adapter):
    c1 = Call(
        name="f1",
        arguments={"a": Digest("a" * 64)},
        metadata={"table": {"m": 1}},
        result=Digest("r" * 64),
    )
    call_storage_adapter.save(c1)

    # Transform: update metadata, keep same key
    def update_metadata(call):
        return replace(call, metadata={"table": {"m": 2}})

    call_storage_adapter.transform(update_metadata)

    assert len(list(call_storage_adapter.list())) == 1
    k1 = c1.to_lookup_key()
    loaded = call_storage_adapter.load(k1)
    assert loaded.metadata == {"table": {"m": 2}}
    assert str(loaded.result) == "r" * 64


def test_transform_key_change(call_storage_adapter):
    c1 = Call(
        name="f1",
        arguments={"a": Digest("a" * 64)},
        metadata={},
        result=Digest("r" * 64),
    )
    call_storage_adapter.save(c1)

    # Transform: change argument, change key
    def change_arg(call):
        return replace(call, arguments={"a": Digest("b" * 64)})

    call_storage_adapter.transform(change_arg)

    all_keys = list(call_storage_adapter.list())
    assert len(all_keys) == 1
    assert c1.to_lookup_key() not in all_keys

    new_c = replace(c1, arguments={"a": Digest("b" * 64)})
    new_k = new_c.to_lookup_key()
    assert new_k in all_keys
    loaded = call_storage_adapter.load(new_k)
    assert str(loaded.arguments["a"]) == "b" * 64
