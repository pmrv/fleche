import pytest
from fleche.config import load_cache_config, load_default_metadata
from fleche.caches import Cache
from fleche.metadata import Runtime

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
