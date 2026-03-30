from fleche.storage.sql import _coerce_sqlite_url


def test_none_returns_memory():
    """Verify _coerce_sqlite_url(None) returns 'sqlite:///:memory:'."""
    assert _coerce_sqlite_url(None) == "sqlite:///:memory:"


def test_sqlite_prefix_preserved():
    """Verify _coerce_sqlite_url('sqlite:foo') returns 'sqlite:foo' unchanged."""
    assert _coerce_sqlite_url("sqlite:foo") == "sqlite:foo"


def test_path_coercion_and_creation(tmp_path):
    """Verify passing a file path returns an absolute URL and creates the parent directory."""
    subdir = tmp_path / "subdir"
    db_file = subdir / "db.sqlite"

    # Ensure directory doesn't exist
    assert not subdir.exists()

    # Coercion should return absolute path and create parent dir
    # Note: _coerce_sqlite_url coerces to absolute path
    url = _coerce_sqlite_url(str(db_file))
    expected = f"sqlite:///{db_file.absolute()}"

    assert url == expected
    assert subdir.exists()
    assert subdir.is_dir()


def test_sqlite_slash_prefix_creation(tmp_path):
    """Verify passing a URL like 'sqlite:////.../db.sqlite' creates the parent directory."""
    subdir = tmp_path / "subdir_url"
    db_file = subdir / "db.sqlite"
    # Create the URL string with absolute path
    url_input = f"sqlite:///{db_file.absolute()}"

    # Ensure directory doesn't exist
    assert not subdir.exists()

    # Coercion should return the URL and create parent dir
    url = _coerce_sqlite_url(url_input)

    assert url == url_input
    assert subdir.exists()
    assert subdir.is_dir()


def test_memory_literal_safety(tmp_path):
    """Verify _coerce_sqlite_url('sqlite:///:memory:') works safely."""
    # This should return the memory URL and NOT attempt to create a directory named ':memory:'
    # or fail.
    assert _coerce_sqlite_url("sqlite:///:memory:") == "sqlite:///:memory:"
