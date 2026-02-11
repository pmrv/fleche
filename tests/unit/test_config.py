import os
import tempfile
from pathlib import Path
import textwrap
import pytest
from dataclasses import dataclass

from fleche import from_config, storage, cache, set_metadata
from fleche.cache import Cache
from fleche import metadata


@dataclass
class NestedStorage(storage.Storage):
    inner: storage.Storage
    arg: str

    def save(self, value, key=None):
        pass

    def load(self, key):
        pass

    def list(self):
        pass


@pytest.fixture
def config_file():
    config = textwrap.dedent("""
        [default]
        cache = "mycache"
        metadata = ["Runtime", "InvocationInfo"]

        [mycache]
        values.type = "Memory"
        invocs.type = "Memory"

        [transient]
        values.type = "CloudpickleFile"
        values.root = ".fleche/values"
        invocs.type = "CloudpickleFile"
        invocs.root = ".fleche/invocs"
        
        [global]
        values.type = "BagOfHoldingH5File"
        values.root = "~/.fleche/values"
        invocs.type = "CloudpickleFile"
        invocs.root = "~/.fleche/invocs"

        [nested]
        values.type = "NestedStorage"
        values.arg = "test"
        values.inner.type = "Memory"
        invocs.type = "Memory"
    """)
    with tempfile.TemporaryDirectory() as tmpdir:
        config_dir = Path(tmpdir) / "fleche"
        config_dir.mkdir()
        config_path = config_dir / "cache.toml"
        config_path.write_text(config)
        yield tmpdir


@pytest.fixture
def config_file_explicit_default():
    config = textwrap.dedent("""
        [default]
        metadata = ["Runtime", "InvocationInfo"]
        [default.cache]
        values.type = "Memory"
        invocs.type = "Memory"
    """)
    with tempfile.TemporaryDirectory() as tmpdir:
        config_dir = Path(tmpdir) / "fleche"
        config_dir.mkdir()
        config_path = config_dir / "cache.toml"
        config_path.write_text(config)
        yield tmpdir


@pytest.fixture
def config_file_with_tags():
    config = textwrap.dedent("""
        [default]
        cache = "mycache"
        metadata = ["Runtime", "InvocationInfo", "Tags"]
    """)
    with tempfile.TemporaryDirectory() as tmpdir:
        config_dir = Path(tmpdir) / "fleche"
        config_dir.mkdir()
        config_path = config_dir / "cache.toml"
        config_path.write_text(config)
        yield tmpdir


@pytest.fixture
def config_file_no_default():
    config = textwrap.dedent("""
        [mycache]
        values.type = "Memory"
        invocs.type = "Memory"
    """)
    with tempfile.TemporaryDirectory() as tmpdir:
        config_dir = Path(tmpdir) / "fleche"
        config_dir.mkdir()
        config_path = config_dir / "cache.toml"
        config_path.write_text(config)
        yield tmpdir


def test_from_config_default(monkeypatch, config_file):
    monkeypatch.setenv("XDG_CONFIG_HOME", config_file)

    cache_obj = from_config()

    assert isinstance(cache_obj, Cache)
    assert isinstance(cache_obj.values, storage.Memory)
    assert isinstance(cache_obj.invocs, storage.Memory)


def test_from_config_explicit_default(monkeypatch, config_file_explicit_default):
    monkeypatch.setenv("XDG_CONFIG_HOME", config_file_explicit_default)

    cache_obj = from_config()

    assert isinstance(cache_obj, Cache)
    assert isinstance(cache_obj.values, storage.Memory)
    assert isinstance(cache_obj.invocs, storage.Memory)


def test_from_config_specific(monkeypatch, config_file):
    monkeypatch.setenv("XDG_CONFIG_HOME", config_file)

    cache_obj = from_config("transient")

    assert isinstance(cache_obj, Cache)
    assert isinstance(cache_obj.values, storage.CloudpickleFile)
    assert cache_obj.values.root == Path(".fleche/values")
    assert isinstance(cache_obj.invocs, storage.CloudpickleFile)
    assert cache_obj.invocs.root == Path(".fleche/invocs")


def test_from_config_no_file(monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", "/tmp/nonexistent")
    cache_obj = from_config()
    assert isinstance(cache_obj, Cache)
    assert isinstance(cache_obj.values, storage.Memory)
    assert isinstance(cache_obj.invocs, storage.Memory)


def test_from_config_no_default(monkeypatch, config_file_no_default):
    monkeypatch.setenv("XDG_CONFIG_HOME", config_file_no_default)
    cache_obj = from_config()
    assert isinstance(cache_obj, Cache)
    assert isinstance(cache_obj.values, storage.Memory)
    assert isinstance(cache_obj.invocs, storage.Memory)


def test_cache_function_loads_by_name(monkeypatch, config_file):
    monkeypatch.setenv("XDG_CONFIG_HOME", config_file)

    with cache("global"):
        cache_obj = cache()
        assert isinstance(cache_obj, Cache)
        assert isinstance(cache_obj.values, storage.BagOfHoldingH5File)
        assert str(cache_obj.values.root) == "~/.fleche/values"


def test_cache_instances_are_persistent(monkeypatch, config_file):
    monkeypatch.setenv("XDG_CONFIG_HOME", config_file)

    with cache("global"):
        cache1 = cache()

    with cache("global"):
        cache2 = cache()

    assert cache1 is cache2


def test_nested_storage(monkeypatch, config_file):
    monkeypatch.setenv("XDG_CONFIG_HOME", config_file)
    storage.NestedStorage = NestedStorage

    cache_obj = from_config("nested")

    assert isinstance(cache_obj, Cache)
    assert isinstance(cache_obj.values, NestedStorage)
    assert cache_obj.values.arg == "test"
    assert isinstance(cache_obj.values.inner, storage.Memory)


def test_load_default_metadata(monkeypatch, config_file):
    monkeypatch.setenv("XDG_CONFIG_HOME", config_file)

    import importlib
    import fleche

    importlib.reload(fleche)

    meta = fleche._METADATA.get()
    assert len(meta) == 2
    assert isinstance(meta[0], metadata.Runtime)
    assert isinstance(meta[1], metadata.InvocationInfo)


def test_load_default_cache(monkeypatch, config_file):
    monkeypatch.setenv("XDG_CONFIG_HOME", config_file)

    import importlib
    import fleche

    importlib.reload(fleche)

    cache_obj = fleche._CACHE.get()
    assert isinstance(cache_obj, Cache)
    assert isinstance(cache_obj.values, storage.Memory)
    assert isinstance(cache_obj.invocs, storage.Memory)


def test_tags_disallowed(monkeypatch, config_file_with_tags):
    monkeypatch.setenv("XDG_CONFIG_HOME", config_file_with_tags)

    import importlib
    import fleche

    with pytest.raises(ValueError):
        importlib.reload(fleche)
