import tempfile
from pathlib import Path
import textwrap
import pytest
from dataclasses import dataclass

from fleche import state, storage, cache
from fleche.config import (
    load_cache_config,
    load_default_metadata,
    _live_caches,
    _load_merged_config,
    _rebase_config,
    _rebase_relative_path,
    _rebase_url,
)
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


@pytest.fixture(autouse=True)
def _reset_fleche_state_defaults():
    """Drop fleche.state's memoised config defaults around each test.

    The tests here patch ``XDG_CONFIG_HOME``, so a default resolved from an
    earlier config file must not leak in either direction.
    """
    state._DEFAULTS.clear()
    yield
    state._DEFAULTS.clear()


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
    # Relative `root` resolves against the declaring file's directory
    # ($XDG_CONFIG_HOME/fleche/cache.toml here), not the CWD (#810).
    assert cache_obj.values.root == Path(config_file) / "fleche" / ".fleche/values"
    assert isinstance(cache_obj.calls, storage.CallPickleFile)
    assert cache_obj.calls.root == Path(config_file) / "fleche" / ".fleche/calls"


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


def test_load_default_metadata(monkeypatch, config_file):
    monkeypatch.setenv("XDG_CONFIG_HOME", config_file)

    meta = state.get_metadata()
    assert len(meta) == 1
    assert isinstance(meta[0], Runtime)


def test_load_default_cache(monkeypatch, config_file):
    monkeypatch.setenv("XDG_CONFIG_HOME", config_file)

    cache_obj = state.get_cache()
    assert isinstance(cache_obj, BaseCache)
    assert isinstance(cache_obj, Cache)
    assert isinstance(cache_obj.values, storage.ValueMemory)
    assert isinstance(cache_obj.calls, storage.CallMemory)


def test_tags_disallowed(monkeypatch, config_file_with_tags):
    monkeypatch.setenv("XDG_CONFIG_HOME", config_file_with_tags)

    with pytest.raises(ValueError):
        state.get_metadata()


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


def _write_config(directory, body, name="fleche.toml"):
    """Write a dedented TOML config file into ``directory``."""
    (directory / name).write_text(textwrap.dedent(body))


@pytest.fixture
def home_and_project(monkeypatch, tmp_path):
    """Lay out ``$HOME=<tmp>`` with CWD at ``<tmp>/project`` and XDG unset.

    Returns ``(home, project)`` so a test only has to write the config
    files whose interaction it is actually exercising.
    """
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    home = tmp_path
    project = home / "project"
    project.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.chdir(project)
    return home, project


def test_walk_root_stops_upward_merge(home_and_project):
    """A closer file with `root = true` blocks farther files from merging in."""
    home, project = home_and_project
    # 'home_only' lives only in the farther ($HOME) file.
    _write_config(home, """
        [home_only]
        values.type = "void"
        calls.type = "void"
    """)
    _write_config(project, """
        [default]
        cache = "home_only"
        root = true
    """)
    # root = true ignores the farther file → 'home_only' unresolved → memory.
    assert isinstance(load_cache_config().values, storage.ValueMemory)


def test_walk_root_keeps_closer_files(monkeypatch, home_and_project):
    """A `root` file still lets files closer to the CWD merge on top."""
    _, root_dir = home_and_project
    nested = root_dir / "nested"
    nested.mkdir()
    monkeypatch.chdir(nested)
    # The root file's own [default] points at a void cache...
    _write_config(root_dir, """
        [default]
        cache = "rootcache"
        root = true

        [rootcache]
        values.type = "void"
        calls.type = "void"

        [nearcache]
        values.type = "memory"
        calls.type = "memory"
    """)
    # ...but the closer file overrides [default] to the memory cache.
    _write_config(nested, """
        [default]
        cache = "nearcache"
    """)
    assert isinstance(load_cache_config().values, storage.ValueMemory)


def test_walk_root_ignores_xdg_fallback(monkeypatch, tmp_path):
    """`root = true` also excludes the XDG lowest-priority fallback."""
    home = tmp_path / "home"
    project = home / "project"
    xdg = tmp_path / "xdg"
    project.mkdir(parents=True)
    (xdg / "fleche").mkdir(parents=True)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg))
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.chdir(project)
    # 'from_xdg' lives only in the XDG fallback layer.
    _write_config(xdg / "fleche", """
        [from_xdg]
        values.type = "void"
        calls.type = "void"
    """, name="cache.toml")
    _write_config(project, """
        [default]
        cache = "from_xdg"
        root = true
    """)
    # XDG layer not merged → 'from_xdg' unresolved → memory fallback.
    assert isinstance(load_cache_config().values, storage.ValueMemory)


def test_walk_root_false_still_merges(home_and_project):
    """`root = false` is a no-op: farther files still merge in."""
    home, project = home_and_project
    _write_config(home, """
        [home_only]
        values.type = "void"
        calls.type = "void"
    """)
    _write_config(project, """
        [default]
        cache = "home_only"
        root = false
    """)
    # root = false → farther file still merged → 'home_only' resolves (void).
    assert isinstance(load_cache_config().values, storage.ValueVoid)


# ---------------------------------------------------------------------------
# Relative path resolution against the declaring file, not the CWD (#810)
# ---------------------------------------------------------------------------


def test_relative_root_resolves_against_config_dir_not_cwd(monkeypatch, home_and_project):
    """A relative `root` anchors to the config file's directory, not the CWD."""
    home, project = home_and_project
    nested = project / "nested" / "deeper"
    nested.mkdir(parents=True)
    monkeypatch.chdir(nested)

    _write_config(project, """
        [default]
        cache = "local"

        [local]
        values.type = "cloudpickle"
        values.root = "fleche/values"
        calls.type = "cloudpickle"
        calls.root = "fleche/calls"
    """)

    cache_obj = load_cache_config()
    assert cache_obj.values.root == project / "fleche" / "values"
    assert cache_obj.calls.root == project / "fleche" / "calls"
    # In particular, NOT anchored to the CWD it happened to be read from.
    assert cache_obj.values.root != nested / "fleche" / "values"


def test_same_config_shares_cache_across_different_cwds(monkeypatch, home_and_project):
    """Reproduces the #810 scenario: one config, read from two CWDs, one cache.

    Before the fix, each CWD resolved the relative `root` against itself,
    silently splitting a single project cache into one private cache per
    working directory.
    """
    home, project = home_and_project
    _write_config(project, """
        [default]
        cache = "local"

        [local]
        values.type = "cloudpickle"
        values.root = "fleche/values"
        calls.type = "cloudpickle"
        calls.root = "fleche/calls"
    """)

    monkeypatch.chdir(project)
    root_from_project = load_cache_config().values.root

    _live_caches.clear()
    state._DEFAULTS.clear()
    deeper = project / "sub" / "deeper"
    deeper.mkdir(parents=True)
    monkeypatch.chdir(deeper)
    root_from_deeper = load_cache_config().values.root

    assert root_from_project == root_from_deeper == project / "fleche" / "values"


def test_relative_root_in_home_file_anchors_to_home_not_project(monkeypatch, home_and_project):
    """A farther ($HOME) file's own relative paths anchor to $HOME, not the CWD."""
    home, project = home_and_project
    _write_config(home, """
        [homecache]
        values.type = "cloudpickle"
        values.root = "fleche/values"
        calls.type = "cloudpickle"
        calls.root = "fleche/calls"
    """)
    _write_config(project, """
        [default]
        cache = "homecache"
    """)

    cache_obj = load_cache_config()
    assert cache_obj.values.root == home / "fleche" / "values"


def test_absolute_root_unaffected(monkeypatch, home_and_project, tmp_path):
    """An absolute `root` is untouched by the rebase."""
    _, project = home_and_project
    elsewhere = tmp_path / "elsewhere"
    _write_config(project, f"""
        [default]
        cache = "local"

        [local]
        values.type = "memory"
        calls.type = "memory"

        [abs]
        values.type = "cloudpickle"
        values.root = "{elsewhere / "values"}"
        calls.type = "cloudpickle"
        calls.root = "{elsewhere / "calls"}"
    """)

    cache_obj = load_cache_config("abs")
    assert cache_obj.values.root == elsewhere / "values"


def test_home_prefixed_root_unaffected(home_and_project):
    """A `~`-prefixed `root` still expands to the user's home, not the config dir."""
    _, project = home_and_project
    _write_config(project, """
        [default]
        cache = "tilde"

        [tilde]
        values.type = "cloudpickle"
        values.root = "~/.fleche/values"
        calls.type = "cloudpickle"
        calls.root = "~/.fleche/calls"
    """)

    cache_obj = load_cache_config()
    assert cache_obj.values.root == Path("~/.fleche/values").expanduser()


def test_relative_sql_url_bare_path_resolves_against_config_dir(home_and_project):
    """A bare relative `calls.url` (sql) anchors to the config file's directory."""
    _, project = home_and_project
    _write_config(project, """
        [default]
        cache = "local"

        [local]
        values.type = "memory"
        calls.type = "sql"
        calls.url = "fleche/calls.db"
    """)

    cache_obj = load_cache_config()
    assert cache_obj.calls.url == f"sqlite:///{project / 'fleche' / 'calls.db'}"


def test_relative_sql_url_scheme_resolves_against_config_dir(home_and_project):
    """A `sqlite:///<relative path>` `calls.url` anchors to the config file's directory."""
    _, project = home_and_project
    _write_config(project, """
        [default]
        cache = "local"

        [local]
        values.type = "memory"
        calls.type = "sql"
        calls.url = "sqlite:///fleche/calls.db"
    """)

    cache_obj = load_cache_config()
    assert cache_obj.calls.url == f"sqlite:///{project / 'fleche' / 'calls.db'}"


def test_absolute_sql_url_unaffected(home_and_project, tmp_path):
    """An absolute `sqlite:////...` `calls.url` is untouched by the rebase."""
    _, project = home_and_project
    db_path = tmp_path / "elsewhere" / "calls.db"
    _write_config(project, f"""
        [default]
        cache = "local"

        [local]
        values.type = "memory"
        calls.type = "sql"
        calls.url = "sqlite:///{db_path}"
    """)

    cache_obj = load_cache_config()
    assert cache_obj.calls.url == f"sqlite:///{db_path}"


def test_memory_sql_url_unaffected(home_and_project):
    """`sqlite:///:memory:` is untouched by the rebase."""
    _, project = home_and_project
    _write_config(project, """
        [default]
        cache = "local"

        [local]
        values.type = "memory"
        calls.type = "sql"
        calls.url = "sqlite:///:memory:"
    """)

    cache_obj = load_cache_config()
    assert cache_obj.calls.url == "sqlite:///:memory:"


def test_ssh_workdir_not_rebased(home_and_project):
    """`workdir` on an `ssh` cache entry names a path on the *remote* host.

    It must not be rewritten as though it were local to the config file —
    only `root`/`url` are treated as local filesystem paths.
    """
    _, project = home_and_project
    _write_config(project, """
        [[shared]]
        values.type = "memory"
        calls.type = "memory"

        [[shared]]
        type = "ssh"
        host = "user@example.com"
        workdir = "relative/remote/dir"
    """)

    config = _load_merged_config()
    ssh_entry = config["shared"][1]
    assert ssh_entry["workdir"] == "relative/remote/dir"


def test_rebase_config_leaves_default_root_boolean_alone():
    """The unrelated boolean `[default].root = true` marker is not a path."""
    base = Path("/some/config/dir")
    config = {"default": {"cache": "x", "root": True}}
    assert _rebase_config(config, base) == {"default": {"cache": "x", "root": True}}


@pytest.mark.parametrize(
    "value, expected",
    [
        ("fleche/values", "/base/fleche/values"),
        ("./fleche/values", "/base/fleche/values"),
        ("/abs/fleche/values", "/abs/fleche/values"),
        ("~/.fleche/values", "~/.fleche/values"),
    ],
)
def test_rebase_relative_path(value, expected):
    assert _rebase_relative_path(value, Path("/base")) == expected


@pytest.mark.parametrize(
    "value, expected",
    [
        ("fleche/calls.db", "/base/fleche/calls.db"),
        ("sqlite:///fleche/calls.db", "sqlite:////base/fleche/calls.db"),
        ("sqlite:////abs/calls.db", "sqlite:////abs/calls.db"),
        ("sqlite:///:memory:", "sqlite:///:memory:"),
        ("sqlite:///~/.fleche/calls.db", "sqlite:///~/.fleche/calls.db"),
        ("postgresql://user@host/db", "postgresql://user@host/db"),
    ],
)
def test_rebase_url(value, expected):
    assert _rebase_url(value, Path("/base")) == expected
