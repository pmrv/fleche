import time
import threading
import tempfile
import socket
from pathlib import Path
import pytest
from fleche.storage import PickleFile
from fleche.digest import digest

def test_load_waits_for_lock():
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = PickleFile.from_pickle(tmpdir)
        key = digest("test")
        data = "content"
        storage.save(data, key=key)

        lock_path = Path(tmpdir) / f"{key}.lock"
        lock_path.write_text("dummy")

        def remove_lock_later():
            time.sleep(0.2)
            lock_path.unlink()

        start = time.perf_counter()
        threading.Thread(target=remove_lock_later).start()

        loaded = storage.load(key)
        end = time.perf_counter()

        assert loaded == data
        assert (end - start) >= 0.2
        print(f"Waited for {(end - start):.3f}s")

def test_load_timeouts_and_reads_anyway(caplog):
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = PickleFile.from_pickle(tmpdir, lock_timeout=0.1)
        key = digest("test")
        data = "content"
        storage.save(data, key=key)

        lock_path = Path(tmpdir) / f"{key}.lock"
        lock_path.write_text("dummy")

        start = time.perf_counter()
        loaded = storage.load(key)
        end = time.perf_counter()

        assert loaded == data
        assert (end - start) >= 0.1
        assert "trying to read anyway" in caplog.text

def test_load_fails_after_timeout_raises_keyerror(caplog):
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = PickleFile.from_pickle(tmpdir, lock_timeout=0.1)
        key = digest("test")
        # Do NOT save data, so load will fail

        lock_path = Path(tmpdir) / f"{key}.lock"
        lock_path.write_text("dummy")

        with pytest.raises(KeyError):
            storage.load(key)

        assert "Failed to read" in caplog.text

def test_save_creates_and_removes_lock(monkeypatch):
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = PickleFile.from_pickle(tmpdir)
        key = digest("test")
        lock_path = storage._path(f"{key}.lock")
        data_path = storage._path(key)

        write_called = False
        def mocked_write_bytes(self, data):
            nonlocal write_called
            if self == data_path:
                assert lock_path.exists()
                content = lock_path.read_text().splitlines()
                assert content[0] == socket.gethostname()
                write_called = True
            return len(data)

        monkeypatch.setattr(Path, "write_bytes", mocked_write_bytes)
        storage.save("data", key=key)
        assert write_called
        assert not lock_path.exists()

def test_list_excludes_locks():
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = PickleFile.from_pickle(tmpdir)
        key = digest("test")
        storage.save("data", key=key)

        lock_path = Path(tmpdir) / f"{key}.lock"
        lock_path.write_text("dummy")

        keys = list(storage.list())
        assert key in keys
        assert len(keys) == 1
        for k in keys:
            assert not k.endswith(".lock")

def test_evict_removes_lock():
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = PickleFile.from_pickle(tmpdir)
        key = digest("test")
        storage.save("data", key=key)

        lock_path = Path(tmpdir) / f"{key}.lock"
        lock_path.write_text("dummy")

        storage.evict(key)
        assert not lock_path.exists()
