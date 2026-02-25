import pytest
from fleche.storage import Memory, DestructuringStorage
from fleche.digest import digest

def test_destructuring_storage_recursive_list():
    mem = Memory(storage={})
    ds = DestructuringStorage(mem)

    data = [1, [2, 3], {"a": 4}]
    key = ds.save(data)

    # Check that it's saved in the underlying memory storage
    assert key in mem.list()

    # Check that components are also saved
    # [2, 3] should be saved
    # {"a": 4} should be saved
    # etc.

    loaded = ds.load(key)
    assert loaded == data
    assert isinstance(loaded, list)
    assert isinstance(loaded[1], list)
    assert isinstance(loaded[2], dict)

def test_destructuring_storage_recursive_dict():
    mem = Memory(storage={})
    ds = DestructuringStorage(mem)

    data = {"k1": [1, 2], "k2": {"inner": "v"}}
    key = ds.save(data)

    loaded = ds.load(key)
    assert loaded == data
    assert isinstance(loaded["k1"], list)
    assert isinstance(loaded["k2"], dict)

def test_destructuring_storage_tuple():
    mem = Memory(storage={})
    ds = DestructuringStorage(mem)

    data = (1, 2, (3, 4))
    key = ds.save(data)

    loaded = ds.load(key)
    assert loaded == data
    assert isinstance(loaded, tuple)
    assert isinstance(loaded[2], tuple)

def test_destructuring_storage_evict():
    mem = Memory(storage={})
    ds = DestructuringStorage(mem)

    data = [1, 2]
    key = ds.save(data)
    assert key in mem.list()

    ds.evict(key)
    assert key not in mem.list()
    with pytest.raises(KeyError):
        ds.load(key)
