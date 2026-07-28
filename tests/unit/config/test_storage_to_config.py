
import threading
from dataclasses import dataclass

import pytest

from fleche import storage
from fleche.storage.base import _STORAGE_CLASSES, _STORAGE_CONSTRUCTORS
from fleche.config import storage_to_config, storage_from_config


@pytest.fixture
def clean_registry():
    """Undo any backend registration a test performs."""
    constructors = dict(_STORAGE_CONSTRUCTORS)
    classes = set(_STORAGE_CLASSES)
    yield
    _STORAGE_CONSTRUCTORS.clear()
    _STORAGE_CONSTRUCTORS.update(constructors)
    _STORAGE_CLASSES.clear()
    _STORAGE_CLASSES.update(classes)


def test_memory():
    s = storage.ValueMemory({})
    assert storage_to_config(s) == {"type": "memory", "remaining_depth": 1}


def test_void():
    s = storage.ValueVoid()
    assert storage_to_config(s) == {"type": "void"}


def test_pickle_file(tmp_path):
    root = tmp_path / "values"
    s = storage.ValuePickleFile.with_pickle(root=root)
    cfg = storage_to_config(s)
    assert cfg["type"] == "pickle"
    assert cfg["root"] == str(s.root)


def test_dill_file(tmp_path):
    pytest.importorskip("dill")
    root = tmp_path / "values"
    s = storage.ValuePickleFile.with_dill(root=root)
    cfg = storage_to_config(s)
    assert cfg["type"] == "dill"
    assert cfg["root"] == str(s.root)


def test_bagofholding_h5file(tmp_path):
    pytest.importorskip("bagofholding")
    root = tmp_path / "values"
    s = storage.ValueBagOfHoldingH5File(root=root)
    cfg = storage_to_config(s)
    assert cfg["type"] == "bagofholding_hdf"
    assert cfg["root"] == str(s.root)
    assert cfg["version_validator"] is None


@pytest.mark.parametrize(
    "version_validator", ["exact", "semantic-minor", "semantic-major", "none"]
)
def test_bagofholding_h5file_version_validator_roundtrip(tmp_path, version_validator):
    pytest.importorskip("bagofholding")
    root = tmp_path / "values"
    original = storage.ValueBagOfHoldingH5File(root=root, version_validator=version_validator)
    cfg = storage_to_config(original)
    assert cfg["type"] == "bagofholding_hdf"
    reconstructed = storage_from_config(cfg, "value")
    assert isinstance(reconstructed, storage.ValueBagOfHoldingH5File)
    assert reconstructed.version_validator == version_validator


def test_bagofholding_h5file_prefix_length_default(tmp_path):
    pytest.importorskip("bagofholding")
    root = tmp_path / "values"
    s = storage.ValueBagOfHoldingH5File(root=root)
    cfg = storage_to_config(s)
    assert cfg["prefix_length"] == 2


@pytest.mark.parametrize("prefix_length", [0, 2, 4])
def test_bagofholding_h5file_prefix_length_roundtrip(tmp_path, prefix_length):
    pytest.importorskip("bagofholding")
    root = tmp_path / "values"
    original = storage.ValueBagOfHoldingH5File(root=root, prefix_length=prefix_length)
    cfg = storage_to_config(original)
    assert cfg["type"] == "bagofholding_hdf"
    reconstructed = storage_from_config(cfg, "value")
    assert isinstance(reconstructed, storage.ValueBagOfHoldingH5File)
    assert reconstructed.prefix_length == prefix_length


def test_bagofholding_h5file_prefix_length_none_roundtrips_resolved(tmp_path):
    """prefix_length=None resolves at construction, so configs round-trip the
    resolved integer rather than the un-inferable None."""
    pytest.importorskip("bagofholding")
    root = tmp_path / "values"
    original = storage.ValueBagOfHoldingH5File(root=root, prefix_length=None)
    cfg = storage_to_config(original)
    assert cfg["prefix_length"] == 2
    reconstructed = storage_from_config(cfg, "value")
    assert reconstructed.prefix_length == 2


def test_sql():
    pytest.importorskip("sqlalchemy")
    s = storage.Sql(url="sqlite:///:memory:")
    cfg = storage_to_config(s)
    assert cfg["type"] == "sql"
    assert cfg["url"] == s.url


def test_unknown_storage_raises():
    class CustomStorage(storage.ValueStorage):
        def put(self, value, key): return key
        def get(self, key): raise KeyError(key)
        def list(self): return ()
        def _evict(self, key): pass
        def _contains(self, key): return False
        def save(self, value, key=None): pass
        def load(self, key): raise KeyError(key)

    with pytest.raises(ValueError, match="CustomStorage"):
        storage_to_config(CustomStorage())


def test_roundtrip_memory():
    cfg = {"type": "memory"}
    s = storage_from_config(cfg, "value")
    assert isinstance(s, storage.ValueMemory)
    assert storage_to_config(s) == {"type": "memory", "remaining_depth": 1}


def test_roundtrip_void():
    cfg = {"type": "void"}
    s = storage_from_config(cfg, "value")
    assert isinstance(s, storage.ValueVoid)
    assert storage_to_config(s) == {"type": "void"}


def test_roundtrip_pickle_file(tmp_path):
    root = tmp_path / "values"
    original = storage.ValuePickleFile.with_pickle(root=root)
    cfg = storage_to_config(original)
    reconstructed = storage_from_config(cfg, "value")
    assert isinstance(reconstructed, storage.ValuePickleFile)
    assert reconstructed.root == original.root


def test_roundtrip_pickle_file_with_secret_key(tmp_path):
    root = tmp_path / "values"
    key = bytes.fromhex("ab" * 32)
    original = storage.ValuePickleFile.with_pickle(root=root, secret_key=[key])
    cfg = storage_to_config(original)
    assert cfg["secret_key"] == [("ab" * 32)]
    reconstructed = storage_from_config(cfg, "value")
    assert isinstance(reconstructed, storage.ValuePickleFile)
    assert reconstructed.secret_key == (key,)


def test_pickle_file_no_secret_key_omitted_from_config(tmp_path):
    root = tmp_path / "values"
    original = storage.ValuePickleFile.with_pickle(root=root, secret_key=[])
    cfg = storage_to_config(original)
    assert "secret_key" not in cfg


def test_storage_from_config_does_not_mutate():
    cfg = {"type": "memory"}
    storage_from_config(cfg, "value")
    assert cfg == {"type": "memory"}


def test_storage_from_config_unknown_type():
    with pytest.raises(ValueError, match="UnknownType"):
        storage_from_config({"type": "UnknownType"}, "value")


def test_storage_from_config_wrong_kind():
    pytest.importorskip("sqlalchemy")
    with pytest.raises(ValueError, match="sql"):
        storage_from_config({"type": "sql", "url": "sqlite:///:memory:"}, "value")


def test_unregistered_subclass_raises():
    """A subclass is not the class that was registered: serialising it as the
    parent's type would silently round-trip back as the parent."""

    @dataclass(frozen=True)
    class MyMemory(storage.ValueMemory):
        __hash__ = object.__hash__

    with pytest.raises(ValueError, match="MyMemory"):
        storage_to_config(MyMemory({}))


def test_memory_config_ignores_undeepcopyable_entries():
    """`to_config` never reads the live store, so what a memory storage happens
    to hold can never break `storage_to_config`."""
    s = storage.ValueMemory({})
    s.storage["a" * 64] = threading.Lock()  # not deep-copyable
    assert storage_to_config(s) == {"type": "memory", "remaining_depth": 1}


def test_register_storage_roundtrips_a_third_party_backend(clean_registry):
    """A new backend needs exactly two things: the decorator (config -> storage)
    and its own to_config (storage -> config).  Nothing is inherited."""

    @storage.register_storage("shouting", kind="value")
    @dataclass(frozen=True)
    class ValueShouting(storage.ValueMixin, storage.StorageBackend):
        volume: int = 11

        def to_config(self):
            return {"type": "shouting", "volume": self.volume}

        def put(self, value, key):
            return key

        def get(self, key):
            raise KeyError(key)

        def list(self):
            return ()

        def _evict(self, key):
            pass

    cfg = storage_to_config(ValueShouting(volume=3))
    assert cfg == {"type": "shouting", "volume": 3}
    reconstructed = storage_from_config(cfg, "value")
    assert isinstance(reconstructed, ValueShouting)
    assert reconstructed.volume == 3
