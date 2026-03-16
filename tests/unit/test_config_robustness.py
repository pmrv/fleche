import os
import pytest
from unittest.mock import patch
from fleche.config import load_cache_config, load_default_metadata
from fleche.caches import Cache
from fleche.metadata import Runtime

def test_load_config_with_syntax_error(tmp_path):
    config_file = tmp_path / "fleche.toml"
    config_file.write_text("invalid = [toml")

    with patch("fleche.config._get_config_path", return_value=config_file):
        # Should not crash and should return a default Memory cache
        cache = load_cache_config()
        assert isinstance(cache, Cache)

        # Should return default metadata
        meta = load_default_metadata()
        assert len(meta) == 1
        assert isinstance(meta[0], Runtime)

def test_load_nonexistent_cache_with_valid_config(tmp_path):
    config_file = tmp_path / "fleche.toml"
    config_file.write_text("[default]\ncache = \"existing\"\n\n[existing]\nvalues.type = \"Memory\"\ncalls.type = \"Memory\"\n")

    with patch("fleche.config._get_config_path", return_value=config_file):
        # Requesting a non-existent cache name
        cache = load_cache_config("nonexistent")
        assert isinstance(cache, Cache)
        # It should fall back to memory, but it's still a Cache object.
        # We can check its storage if we want to be sure.

def test_load_default_metadata_with_syntax_error(tmp_path):
    config_file = tmp_path / "fleche.toml"
    config_file.write_text("default = { metadata = [") # Unterminated

    with patch("fleche.config._get_config_path", return_value=config_file):
        meta = load_default_metadata()
        assert len(meta) == 1
        assert isinstance(meta[0], Runtime)
