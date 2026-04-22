from fleche.call import Call
from fleche.digest import Digest
from fleche.storage import CallMemory


def test_call_storage_overwrite_differing_metadata():
    store = CallMemory({})
    call1 = Call(name="my_func", arguments={"x": 1}, metadata={"tags": {"a": 1}}, result=Digest("1" * 64))
    key1 = store.save(call1)

    assert store.load(key1).metadata == {"tags": {"a": 1}}

    call2 = Call(name="my_func", arguments={"x": 1}, metadata={"tags": {"a": 2}}, result=Digest("1" * 64))
    key2 = store.save(call2)

    assert key1 == key2
    assert store.load(key1).metadata == {"tags": {"a": 2}}
    assert len(list(store.list())) == 1
