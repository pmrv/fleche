import time
import threading
import tempfile
import socket
from pathlib import Path
import pytest
from fleche.storage import PickleFile
from fleche.storage.file import FileStorage
from fleche.digest import digest, Digest
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ConcreteFileStorage(FileStorage):
    def _to_file(self, value: Any, path: Path) -> None:
        pass

    def _from_file(self, path: Path) -> Any:
        return None


def test_file_storage_list_filtering(tmp_path):
    storage = ConcreteFileStorage(root=tmp_path)

    # Create valid files (simulating digests)
    valid_digest1 = "a" * 64
    valid_digest2 = "b" * 64

    (tmp_path / valid_digest1).touch()
    (tmp_path / valid_digest2).touch()

    # Create lock files
    (tmp_path / f"{valid_digest1}.lock").touch()
    (tmp_path / "other.lock").touch()

    # Create a directory (edge case)
    (tmp_path / "subdir").mkdir()

    # Create a hidden file (edge case)
    (tmp_path / ".hidden").touch()

    # Create a hidden directory (edge case)
    (tmp_path / ".hidden_dir").mkdir()

    items = list(storage.list())

    assert Digest(valid_digest1) in items
    assert Digest(valid_digest2) in items
    assert Digest(f"{valid_digest1}.lock") not in items
    assert Digest("other.lock") not in items
    assert Digest("subdir") not in items
    assert Digest(".hidden") not in items
    assert Digest(".hidden_dir") not in items

    assert len(items) == 2


def test_load_waits_for_lock():
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = PickleFile.with_pickle(tmpdir)
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
        storage = PickleFile.with_pickle(tmpdir, lock_timeout=0.1)
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
        storage = PickleFile.with_pickle(tmpdir, lock_timeout=0.1)
        key = digest("test")
        # Do NOT save data, so load will fail

        lock_path = Path(tmpdir) / f"{key}.lock"
        lock_path.write_text("dummy")

        with pytest.raises(KeyError):
            storage.load(key)

        assert "Failed to read" in caplog.text


def test_save_creates_and_removes_lock(monkeypatch):
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = PickleFile.with_pickle(tmpdir)
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
        storage = PickleFile.with_pickle(tmpdir)
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
        storage = PickleFile.with_pickle(tmpdir)
        key = digest("test")
        storage.save("data", key=key)

        lock_path = Path(tmpdir) / f"{key}.lock"
        lock_path.write_text("dummy")

        storage.evict(key)
        assert not lock_path.exists()
