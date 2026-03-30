import pytest
from pathlib import Path
from fleche.storage.file import FileStorage
from fleche.digest import Digest
from dataclasses import dataclass
from typing import Any


@dataclass
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
