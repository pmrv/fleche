import tempfile
from pathlib import Path
import textwrap
import pytest
from dataclasses import dataclass

from fleche import storage, cache
from fleche.config import load_cache_config
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


def _get_values_storage(cache_obj):
    if isinstance(cache_obj.values, storage.DestructuringStorage):
        return cache_obj.values.storage
    return cache_obj.values


def test_load_cache_config_default(monkeypatch, config_file):
    monkeypatch.setenv("XDG_CONFIG_HOME", config_file)

    cache_obj = load_cache_config()

    assert isinstance(cache_obj, Cache)
    assert isinstance(_get_values_storage(cache_obj), storage.Memory)
    assert isinstance(cache_obj.calls, storage.CallStorageAdapter)
    assert isinstance(cache_obj.calls.storage, storage.Memory)


def test_load_cache_config_explicit_default(monkeypatch, config_file_explicit_default):
    monkeypatch.setenv("XDG_CONFIG_HOME", config_file_explicit_default)

    cache_obj = load_cache_config()

    assert isinstance(cache_obj, Cache)
    assert isinstance(_get_values_storage(cache_obj), storage.Memory)
    assert isinstance(cache_obj.calls, storage.CallStorageAdapter)
    assert isinstance(cache_obj.calls.storage, storage.Memory)


def test_load_cache_config_specific(monkeypatch, config_file):
    monkeypatch.setenv("XDG_CONFIG_HOME", config_file)

    cache_obj = load_cache_config("transient")

    assert isinstance(cache_obj, Cache)
    values_storage = _get_values_storage(cache_obj)
    assert isinstance(values_storage, storage.PickleFile)
    assert values_storage.root == Path(".fleche/values").absolute()
    assert isinstance(cache_obj.calls.storage, storage.PickleFile)
    assert cache_obj.calls.storage.root == Path(".fleche/calls").absolute()


def test_load_cache_config_no_file(monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", "/tmp/nonexistent")
    cache_obj = load_cache_config()
    assert isinstance(cache_obj, Cache)
    assert isinstance(_get_values_storage(cache_obj), storage.Memory)
    assert isinstance(cache_obj.calls, storage.CallStorageAdapter)
    assert isinstance(cache_obj.calls.storage, storage.Memory)


def test_load_cache_config_no_default(monkeypatch, config_file_no_default):
    monkeypatch.setenv("XDG_CONFIG_HOME", config_file_no_default)
    cache_obj = load_cache_config()
    assert isinstance(cache_obj, Cache)
    assert isinstance(_get_values_storage(cache_obj), storage.Memory)
    assert isinstance(cache_obj.calls, storage.CallStorageAdapter)
    assert isinstance(cache_obj.calls.storage, storage.Memory)


def test_cache_function_loads_by_name(monkeypatch, config_file):
    monkeypatch.setenv("XDG_CONFIG_HOME", config_file)

    with cache("global"):
        cache_obj = cache()
        assert isinstance(cache_obj, Cache)
        values_storage = _get_values_storage(cache_obj)
        assert isinstance(values_storage, storage.BagOfHoldingH5File)
        assert values_storage.root == Path("~/.fleche/values").expanduser()


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
    values_storage = _get_values_storage(cache_obj)
    assert isinstance(values_storage, NestedStorage)
    assert values_storage.arg == "test"
    assert isinstance(values_storage.inner, storage.Memory)


def test_load_default_metadata(monkeypatch, config_file):
    monkeypatch.setenv("XDG_CONFIG_HOME", config_file)

    import importlib
    import fleche.state

    importlib.reload(fleche.state)

    meta = fleche.state._METADATA.get()
    assert len(meta) == 1
    assert isinstance(meta[0], Runtime)


def test_load_default_cache(monkeypatch, config_file):
    monkeypatch.setenv("XDG_CONFIG_HOME", config_file)

    import importlib
    import fleche.state

    importlib.reload(fleche.state)

    cache_obj = fleche.state._CACHE.get()
    assert isinstance(cache_obj, BaseCache)
    assert isinstance(cache_obj, Cache)
    if hasattr(cache_obj, "values"):
        assert isinstance(_get_values_storage(cache_obj), storage.Memory)
        assert isinstance(cache_obj.calls.storage, storage.Memory)
    else:
        assert isinstance(_get_values_storage(cache_obj.cache), storage.Memory)
        assert isinstance(cache_obj.cache.calls.storage, storage.Memory)


def test_tags_disallowed(monkeypatch, config_file_with_tags):
    monkeypatch.setenv("XDG_CONFIG_HOME", config_file_with_tags)

    import importlib
    import fleche.state

    with pytest.raises(ValueError):
        importlib.reload(fleche.state)


def test_load_cache_config_memory_special_case(monkeypatch, config_file):
    monkeypatch.setenv("XDG_CONFIG_HOME", config_file)

    # Even with a config file that doesn't have 'memory', it should work
    cache1 = load_cache_config("memory")

    assert isinstance(cache1, Cache)
    assert isinstance(_get_values_storage(cache1), storage.Memory)
    assert isinstance(cache1.calls.storage, storage.Memory)

    # Should be a singleton
    cache2 = load_cache_config("memory")
    assert cache1 is cache2


def test_load_cache_config_void_special_case(monkeypatch, config_file):
    monkeypatch.setenv("XDG_CONFIG_HOME", config_file)

    # Even with a config file that doesn't have 'void', it should work
    cache1 = load_cache_config("void")

    assert isinstance(cache1, Cache)
    assert isinstance(_get_values_storage(cache1), storage.Void)
    assert isinstance(cache1.calls.storage, storage.Void)

    # Should be a singleton
    cache2 = load_cache_config("void")
    assert cache1 is cache2


def test_load_cache_config_no_file_singleton(monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", "/tmp/nonexistent")

    cache1 = load_cache_config("memory")
    cache2 = load_cache_config("memory")
    assert cache1 is cache2

    cache_void1 = load_cache_config("void")
    cache_void2 = load_cache_config("void")
    assert cache_void1 is cache_void2
    assert cache1 is not cache_void1
