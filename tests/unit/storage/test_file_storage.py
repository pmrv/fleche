import time
import threading
import filelock
from pathlib import Path
import pytest
from fleche.storage import ValuePickleFile as PickleFile
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

    valid_digest1 = "a" * 64
    valid_digest2 = "b" * 64

    (tmp_path / valid_digest1).touch()
    (tmp_path / valid_digest2).touch()
    (tmp_path / f"{valid_digest1}.lock").touch()
    (tmp_path / "other.lock").touch()
    (tmp_path / "subdir").mkdir()
    (tmp_path / ".hidden").touch()
    (tmp_path / ".hidden_dir").mkdir()

    items = list(storage.list())

    assert len(items) == 2
    assert Digest(valid_digest1) in items
    assert Digest(valid_digest2) in items


def test_load_waits_for_lock(tmp_path):
    storage = PickleFile.with_pickle(tmp_path, lock_timeout=2.0)
    key = digest("test")
    storage.save("content", key=key)

    lock_path = tmp_path / f"{key}.lock"
    holder = filelock.FileLock(lock_path)
    holder.acquire()

    def release_lock_later():
        time.sleep(0.2)
        holder.release()

    threading.Thread(target=release_lock_later).start()
    start = time.perf_counter()
    loaded = storage.load(key)
    assert loaded == "content"
    assert time.perf_counter() - start >= 0.2


def test_load_timeouts_and_reads_anyway(tmp_path, caplog):
    storage = PickleFile.with_pickle(tmp_path, lock_timeout=0.1)
    key = digest("test")
    storage.save("content", key=key)

    lock_path = tmp_path / f"{key}.lock"
    holder = filelock.FileLock(lock_path)
    holder.acquire()
    try:
        loaded = storage.load(key)
        assert loaded == "content"
        assert "trying to read anyway" in caplog.text
    finally:
        holder.release()


def test_load_fails_after_timeout_raises_keyerror(tmp_path, caplog):
    storage = PickleFile.with_pickle(tmp_path, lock_timeout=0.1)
    key = digest("test")

    lock_path = tmp_path / f"{key}.lock"
    holder = filelock.FileLock(lock_path)
    holder.acquire()
    try:
        with pytest.raises(KeyError):
            storage.load(key)
        assert "Failed to read" in caplog.text
    finally:
        holder.release()


def test_save_releases_lock(tmp_path):
    storage = PickleFile.with_pickle(tmp_path)
    key = digest("test")
    storage.save("data", key=key)

    lock_path = tmp_path / f"{key}.lock"
    verifier = filelock.FileLock(lock_path, timeout=0.1)
    verifier.acquire()
    verifier.release()


def test_evict_removes_lock(tmp_path):
    storage = PickleFile.with_pickle(tmp_path)
    key = digest("test")
    storage.save("data", key=key)

    lock_path = tmp_path / f"{key}.lock"
    lock_path.touch()

    storage.evict(key)
    assert not lock_path.exists()
