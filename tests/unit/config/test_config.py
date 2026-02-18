import tempfile
from pathlib import Path
import textwrap
import pytest
from dataclasses import dataclass

from fleche import load_cache_config, storage, cache
from fleche.caches import Cache, BaseCache
from fleche.metadata import Runtime


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
        metadata = ["Runtime"]

        [mycache]
        values.type = "Memory"
        calls.type = "Memory"

        [transient]
        values.type = "CloudpickleFile"
        values.root = ".fleche/values"
        calls.type = "CloudpickleFile"
        calls.root = ".fleche/calls"

        [global]
        values.type = "BagOfHoldingH5File"
        values.root = "~/.fleche/values"
        calls.type = "CloudpickleFile"
        calls.root = "~/.fleche/calls"

        [nested]
        values.type = "NestedStorage"
        values.arg = "test"
        values.inner.type = "Memory"
        calls.type = "Memory"
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
        metadata = ["Runtime"]
        [default.cache]
        values.type = "Memory"
        calls.type = "Memory"
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
        metadata = ["Runtime", "Tags"]
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
        calls.type = "Memory"
    """)
    with tempfile.TemporaryDirectory() as tmpdir:
        config_dir = Path(tmpdir) / "fleche"
        config_dir.mkdir()
        config_path = config_dir / "cache.toml"
        config_path.write_text(config)
        yield tmpdir


def test_load_cache_config_default(monkeypatch, config_file):
    monkeypatch.setenv("XDG_CONFIG_HOME", config_file)

    cache_obj = load_cache_config()

    assert isinstance(cache_obj, Cache)
    assert isinstance(cache_obj.values, storage.Memory)
    assert isinstance(cache_obj.calls, storage.Memory)


def test_load_cache_config_explicit_default(monkeypatch, config_file_explicit_default):
    monkeypatch.setenv("XDG_CONFIG_HOME", config_file_explicit_default)

    cache_obj = load_cache_config()

    assert isinstance(cache_obj, Cache)
    assert isinstance(cache_obj.values, storage.Memory)
    assert isinstance(cache_obj.calls, storage.Memory)


def test_load_cache_config_specific(monkeypatch, config_file):
    monkeypatch.setenv("XDG_CONFIG_HOME", config_file)

    cache_obj = load_cache_config("transient")

    assert isinstance(cache_obj, Cache)
    assert isinstance(cache_obj.values, storage.CloudpickleFile)
    assert cache_obj.values.root == Path(".fleche/values").absolute()
    assert isinstance(cache_obj.calls, storage.CloudpickleFile)
    assert cache_obj.calls.root == Path(".fleche/calls").absolute()


def test_load_cache_config_no_file(monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", "/tmp/nonexistent")
    cache_obj = load_cache_config()
    assert isinstance(cache_obj, Cache)
    assert isinstance(cache_obj.values, storage.Memory)
    assert isinstance(cache_obj.calls, storage.Memory)


def test_load_cache_config_no_default(monkeypatch, config_file_no_default):
    monkeypatch.setenv("XDG_CONFIG_HOME", config_file_no_default)
    cache_obj = load_cache_config()
    assert isinstance(cache_obj, Cache)
    assert isinstance(cache_obj.values, storage.Memory)
    assert isinstance(cache_obj.calls, storage.Memory)


def test_cache_function_loads_by_name(monkeypatch, config_file):
    monkeypatch.setenv("XDG_CONFIG_HOME", config_file)

    with cache("global"):
        cache_obj = cache()
        assert isinstance(cache_obj, Cache)
        assert isinstance(cache_obj.values, storage.BagOfHoldingH5File)
        assert cache_obj.values.root == Path("~/.fleche/values").expanduser()


def test_cache_instances_are_persistent(monkeypatch, config_file):
    monkeypatch.setenv("XDG_CONFIG_HOME", config_file)

    with cache("global"):
        cache1 = cache()

    with cache("global"):
        cache2 = cache()

    assert cache1 is cache2


@pytest.mark.xfail(reason="Missing overloading support for additional storage classes.")
def test_nested_storage(monkeypatch, config_file):
    monkeypatch.setenv("XDG_CONFIG_HOME", config_file)
    storage.NestedStorage = NestedStorage

    cache_obj = load_cache_config("nested")

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
    assert len(meta) == 1
    assert isinstance(meta[0], Runtime)


def test_load_default_cache(monkeypatch, config_file):
    monkeypatch.setenv("XDG_CONFIG_HOME", config_file)

    import importlib
    import fleche

    importlib.reload(fleche)

    cache_obj = fleche._CACHE.get()
    assert isinstance(cache_obj, BaseCache)
    if hasattr(cache_obj, "values"):
        assert isinstance(cache_obj.values, storage.Memory)
        assert isinstance(cache_obj.calls, storage.Memory)
    else:
        assert isinstance(cache_obj.cache.values, storage.Memory)
        assert isinstance(cache_obj.cache.calls, storage.Memory)


def test_tags_disallowed(monkeypatch, config_file_with_tags):
    monkeypatch.setenv("XDG_CONFIG_HOME", config_file_with_tags)

    import importlib
    import fleche

    with pytest.raises(ValueError):
        importlib.reload(fleche)

def test_load_cache_config_memory_special_case(monkeypatch, config_file):
    monkeypatch.setenv("XDG_CONFIG_HOME", config_file)

    # Even with a config file that doesn't have 'memory', it should work
    cache1 = load_cache_config("memory")

    assert isinstance(cache1, Cache)
    assert isinstance(cache1.values, storage.Memory)
    assert isinstance(cache1.calls, storage.Memory)

    # Should be a singleton
    cache2 = load_cache_config("memory")
    assert cache1 is cache2
