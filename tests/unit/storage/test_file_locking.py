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
        storage = PickleFile(tmpdir)
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
        storage = PickleFile(tmpdir, lock_timeout=0.1)
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
        storage = PickleFile(tmpdir, lock_timeout=0.1)
        key = digest("test")
        # Do NOT save data, so load will fail

        lock_path = Path(tmpdir) / f"{key}.lock"
        lock_path.write_text("dummy")

        with pytest.raises(KeyError):
            storage.load(key)

        assert "Failed to read" in caplog.text

def test_save_creates_and_removes_lock():
    with tempfile.TemporaryDirectory() as tmpdir:
        # To verify save creates a lock, we can't easily check it unless we mock _save
        # or use a subclass that checks for lock existence during _save.
        class CheckingPickleFile(PickleFile):
            def _save(self, value, key):
                lock_path = self._path(f"{key}.lock")
                assert lock_path.exists()
                # Check content of lock file
                content = lock_path.read_text().splitlines()
                assert content[0] == socket.gethostname()
                assert int(content[1]) > 0 # pid
                assert float(content[2]) > 0 # timestamp
                return super()._save(value, key)

        storage = CheckingPickleFile(tmpdir)
        key = digest("test")
        storage.save("data", key=key)

        lock_path = Path(tmpdir) / f"{key}.lock"
        assert not lock_path.exists()

def test_list_excludes_locks():
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = PickleFile(tmpdir)
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
        storage = PickleFile(tmpdir)
        key = digest("test")
        storage.save("data", key=key)

        lock_path = Path(tmpdir) / f"{key}.lock"
        lock_path.write_text("dummy")

        storage.evict(key)
        assert not lock_path.exists()
