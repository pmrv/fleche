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


def test_save_creates_no_extra_files(tmp_path):
    storage = PickleFile.with_pickle(tmp_path)
    keys = {storage.save(value) for value in (1, "two", 3.0)}

    assert {p.name for p in tmp_path.iterdir()} == {str(k) for k in keys}


def test_failed_load_creates_no_files(tmp_path):
    storage = PickleFile.with_pickle(tmp_path)

    with pytest.raises(KeyError):
        storage.load("ab" * 32)

    assert list(tmp_path.iterdir()) == []


def test_overwrite_leaves_single_file(tmp_path):
    storage = PickleFile.with_pickle(tmp_path)
    key = digest("test")
    storage.save("first", key=key)
    storage.save("second", key=key)

    assert storage.load(key) == "second"
    assert [p.name for p in tmp_path.iterdir()] == [str(key)]


@dataclass(frozen=True)
class ExplodingFileStorage(FileStorage):
    """Writes half the payload, then dies — an interrupted put."""

    def _to_file(self, value: Any, path: Path) -> None:
        path.write_bytes(b"partial")
        raise RuntimeError("interrupted mid-write")

    def _from_file(self, path: Path) -> Any:
        return path.read_bytes()


def test_interrupted_write_leaves_nothing_behind(tmp_path):
    storage = ExplodingFileStorage(root=tmp_path)
    key = Digest("c" * 64)

    with pytest.raises(RuntimeError):
        storage.put(b"payload", key)

    assert not storage.contains(key)
    assert list(tmp_path.iterdir()) == []


def test_interrupted_rewrite_keeps_old_entry(tmp_path):
    good = ConcreteFileStorage(root=tmp_path)
    key = Digest("d" * 64)
    (tmp_path / str(key)).write_bytes(b"old complete entry")

    bad = ExplodingFileStorage(root=tmp_path)
    with pytest.raises(RuntimeError):
        bad.put(b"payload", key)

    assert (tmp_path / str(key)).read_bytes() == b"old complete entry"
    assert good.contains(key)


def test_evict_removes_entry(tmp_path):
    storage = PickleFile.with_pickle(tmp_path)
    key = digest("test")
    storage.save("data", key=key)

    storage.evict(key)
    assert not (tmp_path / str(key)).exists()


def test_lock_timeout_still_accepted(tmp_path):
    # Deprecated and unused, but configs and call sites from fleche < 2.1
    # pass it; constructing with it must keep working.
    storage = PickleFile.with_pickle(tmp_path, lock_timeout=2.0)
    key = storage.save("data")
    assert storage.load(key) == "data"
