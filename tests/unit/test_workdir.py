
import os
from pathlib import Path
from unittest.mock import patch, MagicMock

from fleche import fleche, cache, Cache, SaveError, PandasDB, storage

def test_get_working_directory_root_default():
    from fleche import _get_working_directory_root
    with patch.dict(os.environ, {}, clear=True):
        expected = Path.home() / '.cache' / 'fleche' / 'workingdirectories'
        assert _get_working_directory_root() == expected

def test_get_working_directory_root_xdg():
    from fleche import _get_working_directory_root
    with patch.dict(os.environ, {'XDG_CACHE_HOME': '/tmp/mycache'}):
        expected = Path('/tmp/mycache') / 'fleche' / 'workingdirectories'
        assert _get_working_directory_root() == expected

def test_fleche_changes_and_restores_cwd():
    original_cwd = os.getcwd()

    @fleche(isolate=True)
    def get_cwd():
        return os.getcwd()

    with cache(Cache(storage.Memory({}), storage.Memory({})).metadb(PandasDB({}))):
        cwd = get_cwd()
        assert cwd != original_cwd
        assert "workingdirectories" in cwd
        assert os.getcwd() == original_cwd

def test_fleche_no_isolate_no_cwd_change():
    original_cwd = os.getcwd()

    @fleche(isolate=False)
    def get_cwd():
        return os.getcwd()

    with cache(Cache(storage.Memory({}), storage.Memory({})).metadb(PandasDB({}))):
        cwd = get_cwd()
        assert cwd == original_cwd

def test_fleche_cleans_up_workdir_on_success():
    workdir_capture = []

    @fleche(isolate=True)
    def my_func():
        cwd = os.getcwd()
        workdir_capture.append(cwd)
        return "success"

    with cache(Cache(storage.Memory({}), storage.Memory({})).metadb(PandasDB({}))):
        my_func()
        workdir = workdir_capture[0]
        assert not os.path.exists(workdir)

def test_fleche_cleans_up_workdir_on_none_result():
    workdir_capture = []

    @fleche(isolate=True)
    def my_func():
        cwd = os.getcwd()
        workdir_capture.append(cwd)
        return None

    with cache(Cache(storage.Memory({}), storage.Memory({})).metadb(PandasDB({}))):
        my_func()
        workdir = workdir_capture[0]
        assert not os.path.exists(workdir)

def test_fleche_cleans_up_on_save_error():
    workdir_capture = []

    @fleche(isolate=True)
    def my_func():
        workdir_capture.append(os.getcwd())
        return "success"

    mock_storage = MagicMock()
    mock_storage.save.side_effect = SaveError("mock save error")

    with cache(Cache(mock_storage, storage.Memory({})).metadb(PandasDB({}))):
        my_func()
        workdir = workdir_capture[0]
        # With TemporaryDirectory, it's cleaned up even on SaveError inside the block
        # (or when the context manager exits)
        assert not os.path.exists(workdir)

def test_distinct_workdirs_for_different_invocations():
    workdirs = []

    @fleche(isolate=True)
    def func(x):
        workdirs.append(os.getcwd())
        return x

    with cache(Cache(storage.Memory({}), storage.Memory({})).metadb(PandasDB({}))):
        func(1)
        func(2)
        assert workdirs[0] != workdirs[1]

def test_distinct_workdirs_for_same_invocation():
    workdirs = []

    @fleche(isolate=True)
    def func(x):
        workdirs.append(os.getcwd())
        return x

    # First call
    with cache(Cache(storage.Memory({}), storage.Memory({})).metadb(PandasDB({}))):
        func(1)

    # Second call (with new cache to force miss)
    with cache(Cache(storage.Memory({}), storage.Memory({})).metadb(PandasDB({}))):
        func(1)

    assert workdirs[0] != workdirs[1]
