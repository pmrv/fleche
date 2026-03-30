import pytest
from fleche.storage import ValueVoid
from fleche.digest import digest


def test_void_storage_save_and_load():
    storage = ValueVoid()
    value = "hello"
    key = digest(value)

    # Save should return the key but do nothing
    returned_key = storage.save(value)
    assert returned_key == key

    # Storage should be empty
    assert list(storage.list()) == []

    # Even after save, load should raise KeyError
    with pytest.raises(KeyError):
        storage.load(key)


def test_void_storage_evict():
    storage = ValueVoid()
    key = digest("something")

    # Evict should do nothing and not raise
    storage.pop(key)


def test_void_storage_expand():
    storage = ValueVoid()

    with pytest.raises(KeyError):
        storage.expand("abcd")
