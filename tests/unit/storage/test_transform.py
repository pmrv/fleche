from dataclasses import replace
from fleche.call import Call
from fleche.digest import Digest
from fleche.storage import CallMemory


def test_transform_basic():
    store = CallMemory({})
    c1 = Call(
        name="f1",
        arguments={"a": Digest("a" * 64)},
        metadata={"table": {"m": 1}},
        result=Digest("r" * 64),
    )
    store.save(c1)

    def update_metadata(call):
        return replace(call, metadata={"table": {"m": 2}})

    store.transform(update_metadata)

    assert len(list(store.list())) == 1
    k1 = c1.to_lookup_key()
    loaded = store.load(k1)
    assert loaded.metadata == {"table": {"m": 2}}
    assert str(loaded.result) == "r" * 64


def test_transform_key_change():
    store = CallMemory({})
    c1 = Call(
        name="f1",
        arguments={"a": Digest("a" * 64)},
        metadata={},
        result=Digest("r" * 64),
    )
    store.save(c1)

    def change_arg(call):
        return replace(call, arguments={"a": Digest("b" * 64)})

    store.transform(change_arg)

    all_keys = list(store.list())
    assert len(all_keys) == 1
    assert c1.to_lookup_key() not in all_keys

    new_c = replace(c1, arguments={"a": Digest("b" * 64)})
    new_k = new_c.to_lookup_key()
    assert new_k in all_keys
    loaded = store.load(new_k)
    assert str(loaded.arguments["a"]) == "b" * 64
