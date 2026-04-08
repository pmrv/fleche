import tempfile
from pathlib import Path
import textwrap
import pytest
from dataclasses import dataclass

from fleche import storage, cache
from fleche.config import load_cache_config, load_default_metadata
from fleche.caches import Cache, BaseCache
from fleche.metadata import Runtime


@pytest.fixture
def config_file():
    config = textwrap.dedent("""
        [default]
        cache = "mycache"
        metadata = ["Runtime"]

        [mycache]
        values.type = "memory"
        calls.type = "memory"

        [transient]
        values.type = "cloudpickle"
        values.root = ".fleche/values"
        calls.type = "cloudpickle"
        calls.root = ".fleche/calls"

        [global]
        values.type = "bagofholding_hdf"
        values.root = "~/.fleche/values"
        calls.type = "cloudpickle"
        calls.root = "~/.fleche/calls"
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
        values.type = "memory"
        calls.type = "memory"
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
        values.type = "memory"
        calls.type = "memory"
    """)
    with tempfile.TemporaryDirectory() as tmpdir:
        config_dir = Path(tmpdir) / "fleche"
        config_dir.mkdir()
        config_path = config_dir / "cache.toml"
        config_path.write_text(config)
        yield tmpdir


@pytest.fixture
def restore_fleche_state():
    """Reload fleche.state after each test to undo any importlib.reload side effects."""
    yield
    import importlib
    import fleche.state
    importlib.reload(fleche.state)


def test_load_cache_config_default(monkeypatch, config_file):
    monkeypatch.setenv("XDG_CONFIG_HOME", config_file)

    cache_obj = load_cache_config()

    assert isinstance(cache_obj, Cache)
    assert isinstance(cache_obj.values, storage.ValueMemory)
    assert isinstance(cache_obj.calls, storage.CallMemory)


def test_load_cache_config_explicit_default(monkeypatch, config_file_explicit_default):
    monkeypatch.setenv("XDG_CONFIG_HOME", config_file_explicit_default)

    cache_obj = load_cache_config()

    assert isinstance(cache_obj, Cache)
    assert isinstance(cache_obj.values, storage.ValueMemory)
    assert isinstance(cache_obj.calls, storage.CallMemory)


def test_load_cache_config_specific(monkeypatch, config_file):
    monkeypatch.setenv("XDG_CONFIG_HOME", config_file)

    cache_obj = load_cache_config("transient")

    assert isinstance(cache_obj, Cache)
    assert isinstance(cache_obj.values, storage.ValuePickleFile)
    assert cache_obj.values.root == Path(".fleche/values").absolute()
    assert isinstance(cache_obj.calls, storage.CallPickleFile)
    assert cache_obj.calls.root == Path(".fleche/calls").absolute()


def test_load_cache_config_no_file(monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", "/tmp/nonexistent")
    cache_obj = load_cache_config()
    assert isinstance(cache_obj, Cache)
    assert isinstance(cache_obj.values, storage.ValueMemory)
    assert isinstance(cache_obj.calls, storage.CallMemory)


def test_load_cache_config_no_default(monkeypatch, config_file_no_default):
    monkeypatch.setenv("XDG_CONFIG_HOME", config_file_no_default)
    cache_obj = load_cache_config()
    assert isinstance(cache_obj, Cache)
    assert isinstance(cache_obj.values, storage.ValueMemory)
    assert isinstance(cache_obj.calls, storage.CallMemory)


def test_cache_function_loads_by_name(monkeypatch, config_file):
    monkeypatch.setenv("XDG_CONFIG_HOME", config_file)

    with cache("global"):
        cache_obj = cache()
        assert isinstance(cache_obj, Cache)
        assert isinstance(cache_obj.values, storage.ValueBagOfHoldingH5File)
        assert cache_obj.values.root == Path("~/.fleche/values").expanduser()


def test_cache_instances_are_persistent(monkeypatch, config_file):
    monkeypatch.setenv("XDG_CONFIG_HOME", config_file)

    with cache("global"):
        cache1 = cache()

    with cache("global"):
        cache2 = cache()

    assert cache1 is cache2


def test_load_default_metadata(restore_fleche_state, monkeypatch, config_file):
    monkeypatch.setenv("XDG_CONFIG_HOME", config_file)

    import importlib
    import fleche.state

    importlib.reload(fleche.state)

    meta = fleche.state._METADATA.get()
    assert len(meta) == 1
    assert isinstance(meta[0], Runtime)


def test_load_default_cache(restore_fleche_state, monkeypatch, config_file):
    monkeypatch.setenv("XDG_CONFIG_HOME", config_file)

    import importlib
    import fleche.state

    importlib.reload(fleche.state)

    cache_obj = fleche.state._CACHE.get()
    assert isinstance(cache_obj, BaseCache)
    assert isinstance(cache_obj, Cache)
    assert isinstance(cache_obj.values, storage.ValueMemory)
    assert isinstance(cache_obj.calls, storage.CallMemory)


def test_tags_disallowed(restore_fleche_state, monkeypatch, config_file_with_tags):
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
    assert isinstance(cache1.values, storage.ValueMemory)
    assert isinstance(cache1.calls, storage.CallMemory)

    # Should be a singleton
    cache2 = load_cache_config("memory")
    assert cache1 is cache2


def test_load_cache_config_void_special_case(monkeypatch, config_file):
    monkeypatch.setenv("XDG_CONFIG_HOME", config_file)

    # Even with a config file that doesn't have 'void', it should work
    cache1 = load_cache_config("void")

    assert isinstance(cache1, Cache)
    assert isinstance(cache1.values, storage.ValueVoid)
    assert isinstance(cache1.calls, storage.CallVoid)

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


# --- Error handling / robustness tests ---

def test_load_config_with_syntax_error(tmp_path, monkeypatch):
    config_dir = tmp_path / "fleche"
    config_dir.mkdir()
    config_file = config_dir / "cache.toml"
    config_file.write_text("invalid = [toml")

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

    # Should not crash and should return a default Memory cache
    cache_obj = load_cache_config()
    assert isinstance(cache_obj, Cache)

    # Should return default metadata
    meta = load_default_metadata()
    assert len(meta) == 1
    assert isinstance(meta[0], Runtime)


def test_load_nonexistent_cache_with_valid_config(tmp_path, monkeypatch):
    config_dir = tmp_path / "fleche"
    config_dir.mkdir()
    config_file = config_dir / "cache.toml"
    config_file.write_text(
        '[default]\ncache = "existing"\n\n[existing]\nvalues.type = "Memory"\ncalls.type = "Memory"\n'
    )

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

    # Requesting a non-existent cache name
    cache_obj = load_cache_config("nonexistent")
    assert isinstance(cache_obj, Cache)


def test_load_default_metadata_with_syntax_error(tmp_path, monkeypatch):
    config_dir = tmp_path / "fleche"
    config_dir.mkdir()
    config_file = config_dir / "cache.toml"
    config_file.write_text("default = { metadata = [")  # Unterminated

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

    meta = load_default_metadata()
    assert len(meta) == 1
    assert isinstance(meta[0], Runtime)
