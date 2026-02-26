import pytest
from fleche.storage import Void
from fleche.digest import digest

def test_void_storage_save_and_load():
    storage = Void()
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
    storage = Void()
    key = digest("something")

    # Evict should do nothing and not raise
    storage.evict(key)

def test_void_storage_expand():
    storage = Void()

    with pytest.raises(KeyError):
        storage.expand("abcd")
