
import os
import shutil
from pathlib import Path
from unittest.mock import patch, MagicMock
from fleche import fleche, cache, Cache, SaveError
from fleche.storage import Memory
from fleche.metadata import PandasDB

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

    @fleche
    def get_cwd():
        return os.getcwd()

    with cache(Cache(Memory({}), Memory({})).metadb(PandasDB({}))):
        cwd = get_cwd()
        assert cwd != original_cwd
        assert "workingdirectories" in cwd
        assert os.getcwd() == original_cwd

def test_fleche_cleans_up_workdir_on_success():
    workdir_capture = []

    @fleche
    def my_func():
        cwd = os.getcwd()
        workdir_capture.append(cwd)
        return "success"

    with cache(Cache(Memory({}), Memory({})).metadb(PandasDB({}))):
        my_func()
        workdir = workdir_capture[0]
        assert not os.path.exists(workdir)

def test_fleche_cleans_up_workdir_on_none_result():
    workdir_capture = []

    @fleche
    def my_func():
        cwd = os.getcwd()
        workdir_capture.append(cwd)
        return None

    with cache(Cache(Memory({}), Memory({})).metadb(PandasDB({}))):
        my_func()
        workdir = workdir_capture[0]
        assert not os.path.exists(workdir)

def test_fleche_does_not_clean_up_on_save_error():
    workdir_capture = []

    @fleche
    def my_func():
        workdir_capture.append(os.getcwd())
        return "success"

    mock_storage = MagicMock()
    mock_storage.save.side_effect = SaveError("mock save error")

    # We need to make sure cache.save(inv) raises SaveError.
    # fleche wrapper catches SaveError and prints it.

    with cache(Cache(mock_storage, Memory({})).metadb(PandasDB({}))):
        my_func()
        workdir = workdir_capture[0]
        # In our implementation, if cache.save raises SaveError, rmtree is skipped.
        assert os.path.exists(workdir)
        # Cleanup for the test
        shutil.rmtree(workdir)

def test_distinct_workdirs_for_different_invocations():
    workdirs = []

    @fleche
    def func(x):
        workdirs.append(os.getcwd())
        return x

    with cache(Cache(Memory({}), Memory({})).metadb(PandasDB({}))):
        func(1)
        func(2)
        assert workdirs[0] != workdirs[1]

def test_distinct_workdirs_for_same_invocation():
    workdirs = []

    @fleche
    def func(x):
        workdirs.append(os.getcwd())
        return x

    # First call
    with cache(Cache(Memory({}), Memory({})).metadb(PandasDB({}))):
        func(1)

    # Second call (with new cache to force miss)
    with cache(Cache(Memory({}), Memory({})).metadb(PandasDB({}))):
        func(1)

    assert workdirs[0] != workdirs[1]
