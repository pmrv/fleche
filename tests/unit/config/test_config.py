import tempfile
from pathlib import Path
import textwrap
import pytest
from dataclasses import dataclass

from fleche import storage, cache
from fleche.config import load_cache_config, load_default_metadata, _live_caches
from fleche.caches import Cache, BaseCache, SizeLimitedCache, ReadOnlyCache, CacheStack
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


@pytest.fixture(autouse=True)
def _reset_live_caches():
    _live_caches.clear()
    yield
    _live_caches.clear()


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


def test_default_cache_is_interned_string_alias(monkeypatch, config_file):
    """The default cache (resolved via a string alias) is interned under None."""
    monkeypatch.setenv("XDG_CONFIG_HOME", config_file)

    assert load_cache_config() is load_cache_config()


def test_default_cache_is_interned_inline_table(monkeypatch, config_file_explicit_default):
    """An inline ``[default.cache]`` table is interned, not rebuilt each call.

    Regression: ``load_cache_config(None)`` used to intern the resolved cache
    under ``"default"`` only, so the ``None`` lookup never hit and every call
    reconstructed the cache — re-spawning an SshCache subprocess for a default
    ssh cache.
    """
    monkeypatch.setenv("XDG_CONFIG_HOME", config_file_explicit_default)

    assert load_cache_config() is load_cache_config()


def test_default_name_is_alias_for_none_string_alias(monkeypatch, config_file):
    """``load_cache_config('default')`` returns the same instance as ``load_cache_config()``."""
    monkeypatch.setenv("XDG_CONFIG_HOME", config_file)

    assert load_cache_config("default") is load_cache_config()


def test_default_name_is_alias_for_none_inline_table(monkeypatch, config_file_explicit_default):
    """``load_cache_config('default')`` returns the same instance as ``load_cache_config()``."""
    monkeypatch.setenv("XDG_CONFIG_HOME", config_file_explicit_default)

    assert load_cache_config("default") is load_cache_config()


def test_cache_default_activates_default_cache(monkeypatch, config_file):
    """``cache('default')`` sets the active cache to the configured default."""
    monkeypatch.setenv("XDG_CONFIG_HOME", config_file)

    default = load_cache_config()
    with cache("default"):
        assert cache() is default


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


def test_fallback_no_config_file_is_singleton(monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", "/tmp/nonexistent")

    default1 = load_cache_config()
    default2 = load_cache_config()
    assert default1 is default2

    named1 = load_cache_config("missing")
    named2 = load_cache_config("missing")
    assert named1 is named2

    assert default1 is not named1


def test_fallback_no_default_in_config_is_singleton(monkeypatch, config_file_no_default):
    monkeypatch.setenv("XDG_CONFIG_HOME", config_file_no_default)

    cache1 = load_cache_config()
    cache2 = load_cache_config()
    assert cache1 is cache2


def test_fallback_named_cache_missing_is_singleton(monkeypatch, config_file_no_default):
    monkeypatch.setenv("XDG_CONFIG_HOME", config_file_no_default)

    cache1 = load_cache_config("nonexistent")
    cache2 = load_cache_config("nonexistent")
    assert cache1 is cache2


# --- TOML parity tests: max_size / read_only / CacheStack ---

@pytest.fixture
def config_file_max_size(tmp_path):
    config = textwrap.dedent("""
        [default]
        cache = "limited"

        [limited]
        values.type = "memory"
        calls.type = "memory"
        max_size = 10
    """)
    config_dir = tmp_path / "fleche"
    config_dir.mkdir()
    (config_dir / "cache.toml").write_text(config)
    return str(tmp_path)


@pytest.fixture
def config_file_read_only(tmp_path):
    config = textwrap.dedent("""
        [default]
        cache = "readonly"

        [readonly]
        values.type = "memory"
        calls.type = "memory"
        read_only = true
    """)
    config_dir = tmp_path / "fleche"
    config_dir.mkdir()
    (config_dir / "cache.toml").write_text(config)
    return str(tmp_path)


@pytest.fixture
def config_file_cache_stack(tmp_path):
    config = textwrap.dedent("""
        [default]
        cache = "mystack"

        [[mystack]]
        values.type = "memory"
        calls.type = "memory"

        [[mystack]]
        values.type = "void"
        calls.type = "void"
    """)
    config_dir = tmp_path / "fleche"
    config_dir.mkdir()
    (config_dir / "cache.toml").write_text(config)
    return str(tmp_path)


def test_load_cache_config_max_size(monkeypatch, config_file_max_size):
    monkeypatch.setenv("XDG_CONFIG_HOME", config_file_max_size)

    cache_obj = load_cache_config()

    assert isinstance(cache_obj, SizeLimitedCache)
    assert cache_obj.max_size == 10
    assert isinstance(cache_obj.values, storage.ValueMemory)
    assert isinstance(cache_obj.calls, storage.CallMemory)


def test_load_cache_config_read_only(monkeypatch, config_file_read_only):
    monkeypatch.setenv("XDG_CONFIG_HOME", config_file_read_only)

    cache_obj = load_cache_config()

    assert isinstance(cache_obj, ReadOnlyCache)
    assert isinstance(cache_obj.cache, Cache)
    assert isinstance(cache_obj.cache.values, storage.ValueMemory)
    assert isinstance(cache_obj.cache.calls, storage.CallMemory)


def test_load_cache_config_cache_stack(monkeypatch, config_file_cache_stack):
    monkeypatch.setenv("XDG_CONFIG_HOME", config_file_cache_stack)

    cache_obj = load_cache_config()

    assert isinstance(cache_obj, CacheStack)
    assert len(cache_obj.stack) == 2
    assert isinstance(cache_obj.stack[0], Cache)
    assert isinstance(cache_obj.stack[0].values, storage.ValueMemory)
    assert isinstance(cache_obj.stack[1], Cache)
    assert isinstance(cache_obj.stack[1].values, storage.ValueVoid)


def test_load_cache_config_max_size_by_name(monkeypatch, config_file_max_size):
    monkeypatch.setenv("XDG_CONFIG_HOME", config_file_max_size)

    cache_obj = load_cache_config("limited")

    assert isinstance(cache_obj, SizeLimitedCache)
    assert cache_obj.max_size == 10


def test_load_cache_config_read_only_by_name(monkeypatch, config_file_read_only):
    monkeypatch.setenv("XDG_CONFIG_HOME", config_file_read_only)

    cache_obj = load_cache_config("readonly")

    assert isinstance(cache_obj, ReadOnlyCache)


def test_load_cache_config_cache_stack_by_name(monkeypatch, config_file_cache_stack):
    monkeypatch.setenv("XDG_CONFIG_HOME", config_file_cache_stack)

    cache_obj = load_cache_config("mystack")

    assert isinstance(cache_obj, CacheStack)
    assert len(cache_obj.stack) == 2


# --- Walking config discovery (CWD → HOME → XDG fallback) ---


def test_walk_picks_up_local_fleche_toml(monkeypatch, tmp_path):
    """A fleche.toml in the CWD is discovered without XDG."""
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.chdir(tmp_path)

    (tmp_path / "fleche.toml").write_text(textwrap.dedent("""
        [default]
        cache = "local"

        [local]
        values.type = "memory"
        calls.type = "memory"
    """))

    cache_obj = load_cache_config()
    assert isinstance(cache_obj, Cache)
    assert isinstance(cache_obj.values, storage.ValueMemory)


def test_walk_picks_up_dotfile_in_home(monkeypatch, tmp_path):
    """A fleche.toml in $HOME is discovered as the walk reaches it."""
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    home = tmp_path
    sub = home / "project"
    sub.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.chdir(sub)

    (home / "fleche.toml").write_text(textwrap.dedent("""
        [default]
        cache = "fromhome"

        [fromhome]
        values.type = "void"
        calls.type = "void"
    """))

    cache_obj = load_cache_config()
    assert isinstance(cache_obj, Cache)
    assert isinstance(cache_obj.values, storage.ValueVoid)


def test_walk_closer_overrides_farther(monkeypatch, tmp_path):
    """A fleche.toml closer to CWD overrides a farther one (shallow merge)."""
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    home = tmp_path
    sub = home / "project"
    sub.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.chdir(sub)

    # Farther file: $HOME/fleche.toml — picks 'far' (Void) as default
    (home / "fleche.toml").write_text(textwrap.dedent("""
        [default]
        cache = "far"

        [far]
        values.type = "void"
        calls.type = "void"
    """))

    # Closer file: CWD/fleche.toml — overrides [default] to point at 'near'
    (sub / "fleche.toml").write_text(textwrap.dedent("""
        [default]
        cache = "near"

        [near]
        values.type = "memory"
        calls.type = "memory"
    """))

    cache_obj = load_cache_config()
    # closer file's [default] wins → 'near' (memory)
    assert isinstance(cache_obj.values, storage.ValueMemory)


def test_walk_merges_disjoint_tables(monkeypatch, tmp_path):
    """A cache defined only in a farther file is still accessible by name."""
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    home = tmp_path
    sub = home / "project"
    sub.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.chdir(sub)

    (home / "fleche.toml").write_text(textwrap.dedent("""
        [home_only]
        values.type = "void"
        calls.type = "void"
    """))

    (sub / "fleche.toml").write_text(textwrap.dedent("""
        [default]
        cache = "home_only"
    """))

    cache_obj = load_cache_config()
    assert isinstance(cache_obj.values, storage.ValueVoid)


def test_walk_xdg_is_lowest_priority(monkeypatch, tmp_path):
    """XDG config is the lowest-priority layer; closer fleche.toml overrides."""
    home = tmp_path / "home"
    home.mkdir()
    sub = home / "project"
    sub.mkdir()
    xdg = tmp_path / "xdg"
    (xdg / "fleche").mkdir(parents=True)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg))
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.chdir(sub)

    (xdg / "fleche" / "cache.toml").write_text(textwrap.dedent("""
        [default]
        cache = "from_xdg"

        [from_xdg]
        values.type = "void"
        calls.type = "void"
    """))

    (sub / "fleche.toml").write_text(textwrap.dedent("""
        [default]
        cache = "local"

        [local]
        values.type = "memory"
        calls.type = "memory"
    """))

    cache_obj = load_cache_config()
    assert isinstance(cache_obj.values, storage.ValueMemory)


def test_walk_stops_at_home(monkeypatch, tmp_path):
    """A fleche.toml above $HOME is not picked up by the walk."""
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    above_home = tmp_path
    home = above_home / "home"
    home.mkdir()
    sub = home / "project"
    sub.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.chdir(sub)

    # This file sits ABOVE $HOME — must be ignored.
    (above_home / "fleche.toml").write_text(textwrap.dedent("""
        [default]
        cache = "above"

        [above]
        values.type = "void"
        calls.type = "void"
    """))

    cache_obj = load_cache_config()
    # No config found within walk → default memory fallback
    assert isinstance(cache_obj.values, storage.ValueMemory)


def test_walk_xdg_used_when_no_walk_hits(monkeypatch, tmp_path):
    """If nothing is found in the walk, XDG still works (back-compat)."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.chdir(home)

    xdg = tmp_path / "xdg"
    (xdg / "fleche").mkdir(parents=True)
    (xdg / "fleche" / "cache.toml").write_text(textwrap.dedent("""
        [default]
        cache = "from_xdg"

        [from_xdg]
        values.type = "void"
        calls.type = "void"
    """))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg))

    cache_obj = load_cache_config()
    assert isinstance(cache_obj.values, storage.ValueVoid)


def test_walk_xdg_defaults_to_home_config_when_unset(monkeypatch, tmp_path):
    """Per the XDG spec, an unset XDG_CONFIG_HOME means $HOME/.config."""
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.chdir(home)

    (home / ".config" / "fleche").mkdir(parents=True)
    (home / ".config" / "fleche" / "cache.toml").write_text(textwrap.dedent("""
        [default]
        cache = "from_default_xdg"

        [from_default_xdg]
        values.type = "void"
        calls.type = "void"
    """))

    cache_obj = load_cache_config()
    assert isinstance(cache_obj.values, storage.ValueVoid)


def test_walk_xdg_defaults_to_home_config_when_empty(monkeypatch, tmp_path):
    """Per the XDG spec, an empty XDG_CONFIG_HOME also falls back to $HOME/.config."""
    monkeypatch.setenv("XDG_CONFIG_HOME", "")
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.chdir(home)

    (home / ".config" / "fleche").mkdir(parents=True)
    (home / ".config" / "fleche" / "cache.toml").write_text(textwrap.dedent("""
        [default]
        cache = "from_default_xdg"

        [from_default_xdg]
        values.type = "void"
        calls.type = "void"
    """))

    cache_obj = load_cache_config()
    assert isinstance(cache_obj.values, storage.ValueVoid)


def test_walk_merged_metadata(monkeypatch, tmp_path):
    """load_default_metadata also consults the merged config."""
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    home = tmp_path
    sub = home / "project"
    sub.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.chdir(sub)

    (home / "fleche.toml").write_text(textwrap.dedent("""
        [default]
        metadata = ["Runtime"]
    """))

    meta = load_default_metadata()
    assert len(meta) == 1
    assert isinstance(meta[0], Runtime)


def test_walk_root_stops_upward_merge(monkeypatch, tmp_path):
    """A closer file with `root = true` blocks farther files from merging in."""
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    home = tmp_path
    sub = home / "project"
    sub.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.chdir(sub)

    # Farther file defines a cache the closer file references by name.
    (home / "fleche.toml").write_text(textwrap.dedent("""
        [home_only]
        values.type = "void"
        calls.type = "void"
    """))

    # Closer file declares itself root → the farther file is ignored, so
    # 'home_only' is not resolvable and we fall back to the memory default.
    (sub / "fleche.toml").write_text(textwrap.dedent("""
        [default]
        cache = "home_only"
        root = true
    """))

    cache_obj = load_cache_config()
    # 'home_only' was never merged → fallback memory cache.
    assert isinstance(cache_obj.values, storage.ValueMemory)


def test_walk_root_keeps_closer_files(monkeypatch, tmp_path):
    """`root` stops farther files but closer files still merge on top."""
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    home = tmp_path
    mid = home / "project"
    mid.mkdir()
    sub = mid / "nested"
    sub.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.chdir(sub)

    # Farthest ($HOME) — must be ignored because 'mid' is root.
    (home / "fleche.toml").write_text(textwrap.dedent("""
        [default]
        cache = "from_home"

        [from_home]
        values.type = "void"
        calls.type = "void"
    """))

    # Middle — the root of the hierarchy; supplies the 'chosen' cache.
    (mid / "fleche.toml").write_text(textwrap.dedent("""
        [default]
        cache = "from_home"
        root = true

        [chosen]
        values.type = "memory"
        calls.type = "memory"
    """))

    # Closest — still merges on top of the root file, overriding [default].
    (sub / "fleche.toml").write_text(textwrap.dedent("""
        [default]
        cache = "chosen"
    """))

    cache_obj = load_cache_config()
    # Closer file's [default] wins ('chosen'); farther $HOME file is ignored.
    assert isinstance(cache_obj.values, storage.ValueMemory)


def test_walk_root_ignores_xdg_fallback(monkeypatch, tmp_path):
    """`root = true` also excludes the XDG lowest-priority fallback."""
    home = tmp_path / "home"
    home.mkdir()
    sub = home / "project"
    sub.mkdir()
    xdg = tmp_path / "xdg"
    (xdg / "fleche").mkdir(parents=True)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg))
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.chdir(sub)

    (xdg / "fleche" / "cache.toml").write_text(textwrap.dedent("""
        [from_xdg]
        values.type = "void"
        calls.type = "void"
    """))

    (sub / "fleche.toml").write_text(textwrap.dedent("""
        [default]
        cache = "from_xdg"
        root = true
    """))

    cache_obj = load_cache_config()
    # XDG layer was not merged → 'from_xdg' unresolved → memory fallback.
    assert isinstance(cache_obj.values, storage.ValueMemory)


def test_walk_root_false_still_merges(monkeypatch, tmp_path):
    """`root = false` is a no-op: farther files still merge in."""
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    home = tmp_path
    sub = home / "project"
    sub.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.chdir(sub)

    (home / "fleche.toml").write_text(textwrap.dedent("""
        [home_only]
        values.type = "void"
        calls.type = "void"
    """))

    (sub / "fleche.toml").write_text(textwrap.dedent("""
        [default]
        cache = "home_only"
        root = false
    """))

    cache_obj = load_cache_config()
    # root = false → farther file still merged → 'home_only' resolves.
    assert isinstance(cache_obj.values, storage.ValueVoid)
