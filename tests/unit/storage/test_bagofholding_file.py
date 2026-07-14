import logging
from unittest.mock import MagicMock

import pytest

from fleche.digest import Digest
from fleche.storage.bagofholding_file import BagOfHoldingH5FileBackend


def test_load_corrupt_h5_file(tmp_path, caplog):
    storage = BagOfHoldingH5FileBackend(tmp_path)

    key = Digest("corrupt_key")
    path = storage._path(key)
    path.parent.mkdir(parents=True, exist_ok=True)

    # Write corrupt/invalid HDF5 file
    path.write_bytes(b"this is not a valid hdf5 file")

    with caplog.at_level(logging.ERROR, logger="fleche.storage.bagofholding_file"):
        with pytest.raises(KeyError):
            storage.get(key)

    assert f"Corrupt file present in cache at path {path}" in caplog.text


def test_version_validator_default_is_none(tmp_path):
    pytest.importorskip("bagofholding")
    s = BagOfHoldingH5FileBackend(tmp_path)
    assert s.version_validator is None


def test_version_validator_field_accepted(tmp_path):
    pytest.importorskip("bagofholding")
    s = BagOfHoldingH5FileBackend(tmp_path, version_validator="none")
    assert s.version_validator == "none"


def test_version_validator_passed_to_load(tmp_path, monkeypatch):
    pytest.importorskip("bagofholding")
    import fleche.storage.bagofholding_file as boh_mod

    mock_h5bag = MagicMock()
    mock_h5bag.return_value.load.return_value = 42
    monkeypatch.setattr(boh_mod, "H5Bag", mock_h5bag)

    s = BagOfHoldingH5FileBackend(tmp_path, version_validator="semantic-minor")
    key = Digest("test_key")
    s.put(42, key)
    result = s.get(key)

    assert result == 42
    mock_h5bag.return_value.load.assert_called_with(version_validator="semantic-minor")


def test_version_validator_none_not_passed_to_load(tmp_path, monkeypatch):
    pytest.importorskip("bagofholding")
    import fleche.storage.bagofholding_file as boh_mod

    mock_h5bag = MagicMock()
    mock_h5bag.return_value.load.return_value = 42
    monkeypatch.setattr(boh_mod, "H5Bag", mock_h5bag)

    s = BagOfHoldingH5FileBackend(tmp_path)
    key = Digest("test_key2")
    s.put(42, key)
    s.get(key)

    _, kwargs = mock_h5bag.return_value.load.call_args
    assert "version_validator" not in kwargs


def test_rebag_calls_load_and_save(tmp_path, monkeypatch):
    pytest.importorskip("bagofholding")
    import fleche.storage.bagofholding_file as boh_mod

    mock_h5bag = MagicMock()
    mock_h5bag.return_value.load.return_value = 99
    monkeypatch.setattr(boh_mod, "H5Bag", mock_h5bag)

    s = BagOfHoldingH5FileBackend(tmp_path)
    key = Digest("resave_key")
    s._path(key).write_bytes(b"dummy")

    s.rebag(version_validator="none")

    mock_h5bag.return_value.load.assert_called_once_with(version_validator="none")
    mock_h5bag.save.assert_called_once_with(99, s._path(key))


def test_rebag_skips_oserror(tmp_path, monkeypatch, caplog):
    pytest.importorskip("bagofholding")
    import fleche.storage.bagofholding_file as boh_mod

    mock_h5bag = MagicMock()
    mock_h5bag.return_value.load.side_effect = OSError("broken bag")
    monkeypatch.setattr(boh_mod, "H5Bag", mock_h5bag)

    s = BagOfHoldingH5FileBackend(tmp_path)
    key = Digest("broken_key")
    s._path(key).write_bytes(b"dummy")

    with caplog.at_level(logging.WARNING, logger="fleche.storage.bagofholding_file"):
        s.rebag(version_validator="none")  # should not raise

    assert "Failed to rebag" in caplog.text


def test_from_file_passes_skip_load_to_h5bag(tmp_path, monkeypatch):
    """_from_file must pass _skip_load=True so the file is opened only once per get."""
    pytest.importorskip("bagofholding")
    import fleche.storage.bagofholding_file as boh_mod

    mock_h5bag = MagicMock()
    mock_h5bag.return_value.load.return_value = 7
    monkeypatch.setattr(boh_mod, "H5Bag", mock_h5bag)

    s = BagOfHoldingH5FileBackend(tmp_path)
    key = Digest("skip_load_key")
    s.get(key)

    _, kwargs = mock_h5bag.call_args
    assert kwargs.get("_skip_load") is True


def test_rebag_passes_skip_load_to_h5bag(tmp_path, monkeypatch):
    """rebag must pass _skip_load=True so the file is opened only once per entry."""
    pytest.importorskip("bagofholding")
    import fleche.storage.bagofholding_file as boh_mod

    mock_h5bag = MagicMock()
    mock_h5bag.return_value.load.return_value = 1
    monkeypatch.setattr(boh_mod, "H5Bag", mock_h5bag)

    s = BagOfHoldingH5FileBackend(tmp_path)
    key = Digest("rebag_skip_load_key")
    s._path(key).write_bytes(b"dummy")

    s.rebag()

    _, kwargs = mock_h5bag.call_args
    assert kwargs.get("_skip_load") is True


def test_rebag_default_validator_is_none(tmp_path, monkeypatch):
    pytest.importorskip("bagofholding")
    import fleche.storage.bagofholding_file as boh_mod

    mock_h5bag = MagicMock()
    mock_h5bag.return_value.load.return_value = 1
    monkeypatch.setattr(boh_mod, "H5Bag", mock_h5bag)

    s = BagOfHoldingH5FileBackend(tmp_path)
    key = Digest("default_key")
    s._path(key).write_bytes(b"dummy")

    s.rebag()

    mock_h5bag.return_value.load.assert_called_once_with(version_validator="none")


def _digest_like(payload: str) -> Digest:
    # 64-char stand-ins for real sha256 digests, so prefix slicing behaves realistically.
    return Digest((payload * 64)[:64])


def test_multi_bag_put_get_roundtrip(tmp_path):
    pytest.importorskip("bagofholding")
    s = BagOfHoldingH5FileBackend(tmp_path, prefix_length=2)
    key = _digest_like("a")

    s.put("hello", key)

    assert s.get(key) == "hello"
    assert (tmp_path / f"{key[:2]}.h5").is_file()


def test_multi_bag_single_file_multiple_keys(tmp_path):
    pytest.importorskip("bagofholding")
    s = BagOfHoldingH5FileBackend(tmp_path, prefix_length=2)
    key1 = Digest("ab" + "1" * 62)
    key2 = Digest("ab" + "2" * 62)

    s.put("first", key1)
    s.put("second", key2)

    assert s.get(key1) == "first"
    assert s.get(key2) == "second"
    h5_files = list(tmp_path.glob("*.h5"))
    assert len(h5_files) == 1
    assert h5_files[0].name == "ab.h5"


def test_multi_bag_list(tmp_path):
    pytest.importorskip("bagofholding")
    s = BagOfHoldingH5FileBackend(tmp_path, prefix_length=2)
    key1 = Digest("ab" + "1" * 62)
    key2 = Digest("cd" + "2" * 62)

    s.put("first", key1)
    s.put("second", key2)

    assert set(s.list()) == {key1, key2}


def test_multi_bag_evict(tmp_path):
    pytest.importorskip("bagofholding")
    s = BagOfHoldingH5FileBackend(tmp_path, prefix_length=2)
    key1 = Digest("ab" + "1" * 62)
    key2 = Digest("ab" + "2" * 62)

    s.put("first", key1)
    s.put("second", key2)

    s.evict(key1)
    assert not s.contains(key1)
    assert s.contains(key2)
    assert (tmp_path / "ab.h5").is_file()  # sibling group survives

    s.evict(key2)
    assert not s.contains(key2)
    assert not (tmp_path / "ab.h5").exists()  # file removed once empty


def test_multi_bag_contains(tmp_path):
    pytest.importorskip("bagofholding")
    s = BagOfHoldingH5FileBackend(tmp_path, prefix_length=2)
    key = _digest_like("a")
    missing = _digest_like("b")

    assert not s.contains(key)
    s.put("value", key)
    assert s.contains(key)
    assert not s.contains(missing)


def test_multi_bag_different_prefix_lengths(tmp_path):
    pytest.importorskip("bagofholding")
    s2 = BagOfHoldingH5FileBackend(tmp_path / "two", prefix_length=2)
    s4 = BagOfHoldingH5FileBackend(tmp_path / "four", prefix_length=4)
    key = _digest_like("a")

    s2.put("short-prefix", key)
    s4.put("long-prefix", key)

    assert (tmp_path / "two" / f"{key[:2]}.h5").is_file()
    assert (tmp_path / "four" / f"{key[:4]}.h5").is_file()
    assert s2.get(key) == "short-prefix"
    assert s4.get(key) == "long-prefix"


def test_refix_from_per_key(tmp_path):
    pytest.importorskip("bagofholding")
    s = BagOfHoldingH5FileBackend(tmp_path)
    key1 = Digest("ab" + "1" * 62)
    key2 = Digest("cd" + "2" * 62)
    s.put("first", key1)
    s.put("second", key2)

    s.refix(2)

    assert s.prefix_length == 2
    assert not (tmp_path / key1).exists()
    assert not (tmp_path / key2).exists()
    assert {p.name for p in tmp_path.glob("*.h5")} == {"ab.h5", "cd.h5"}
    assert s.get(key1) == "first"
    assert s.get(key2) == "second"


def test_refix_to_per_key(tmp_path):
    pytest.importorskip("bagofholding")
    s = BagOfHoldingH5FileBackend(tmp_path, prefix_length=2)
    key1 = Digest("ab" + "1" * 62)
    key2 = Digest("ab" + "2" * 62)
    s.put("first", key1)
    s.put("second", key2)

    s.refix(None)

    assert s.prefix_length is None
    assert not list(tmp_path.glob("*.h5"))
    assert (tmp_path / key1).is_file()
    assert (tmp_path / key2).is_file()
    assert s.get(key1) == "first"
    assert s.get(key2) == "second"


def test_refix_between_prefixes(tmp_path):
    pytest.importorskip("bagofholding")
    s = BagOfHoldingH5FileBackend(tmp_path, prefix_length=2)
    key1 = Digest("ab" + "1" * 62)
    key2 = Digest("ab" + "2" * 62)
    s.put("first", key1)
    s.put("second", key2)

    s.refix(4)

    assert s.prefix_length == 4
    assert {p.name for p in tmp_path.glob("*.h5")} == {"ab11.h5", "ab22.h5"}
    assert s.get(key1) == "first"
    assert s.get(key2) == "second"


def test_refix_noop(tmp_path):
    pytest.importorskip("bagofholding")
    s = BagOfHoldingH5FileBackend(tmp_path, prefix_length=2)
    key = _digest_like("a")
    s.put("value", key)

    s.refix(2)

    assert s.prefix_length == 2
    assert s.get(key) == "value"


def test_refix_unlinks_old_bags_as_soon_as_drained(tmp_path, monkeypatch):
    """Each old bag must be gone before the next one's entries are copied,
    so disk usage never balloons beyond one bag's worth of duplicates."""
    pytest.importorskip("bagofholding")
    import fleche.storage.bagofholding_file as boh_mod
    from pathlib import Path

    s = BagOfHoldingH5FileBackend(tmp_path, prefix_length=2)
    key1 = Digest("ab" + "1" * 62)
    key2 = Digest("cd" + "2" * 62)
    s.put("first", key1)
    s.put("second", key2)

    real_save = boh_mod.H5Bag.save
    bags_at_save = {}

    def spying_save(value, path):
        bags_at_save[Path(path).name] = {p.name for p in tmp_path.glob("*.h5")}
        return real_save(value, path)

    monkeypatch.setattr(boh_mod.H5Bag, "save", staticmethod(spying_save))

    s.refix(4)

    # bags are drained in sorted order, so ab.h5 must already be unlinked by
    # the time cd.h5's entry is copied into the new layout
    assert "ab.h5" not in bags_at_save[str(key2)]
    assert s.get(key1) == "first"
    assert s.get(key2) == "second"


def test_refix_keeps_unreadable_entries_in_old_layout(tmp_path, monkeypatch):
    pytest.importorskip("bagofholding")
    import h5py

    s = BagOfHoldingH5FileBackend(tmp_path, prefix_length=2)
    key1 = Digest("ab" + "1" * 62)
    key2 = Digest("ab" + "2" * 62)
    s.put("first", key1)
    s.put("second", key2)

    real_from_file = BagOfHoldingH5FileBackend._from_file

    def failing_from_file(self, path):
        if path.name == key1:
            raise KeyError(path)
        return real_from_file(self, path)

    monkeypatch.setattr(BagOfHoldingH5FileBackend, "_from_file", failing_from_file)

    s.refix(None)

    # the migrated sibling moved out and was dropped from the old bag, the
    # unreadable entry stayed behind
    assert (tmp_path / key2).is_file()
    assert (tmp_path / "ab.h5").is_file()
    with h5py.File(tmp_path / "ab.h5", "r") as f:
        assert set(f.keys()) == {key1}


def test_refix_rejects_invalid(tmp_path):
    pytest.importorskip("bagofholding")
    s = BagOfHoldingH5FileBackend(tmp_path)
    with pytest.raises(ValueError, match="prefix_length"):
        s.refix(0)
    with pytest.raises(ValueError, match="prefix_length"):
        s.refix(65)


def test_reopen_after_refix(tmp_path):
    pytest.importorskip("bagofholding")
    s = BagOfHoldingH5FileBackend(tmp_path)
    key = _digest_like("a")
    s.put("value", key)

    s.refix(2)

    reopened = BagOfHoldingH5FileBackend(tmp_path, prefix_length=2)
    assert reopened.get(key) == "value"


def test_init_rejects_invalid_prefix_length(tmp_path):
    pytest.importorskip("bagofholding")
    with pytest.raises(ValueError, match="prefix_length"):
        BagOfHoldingH5FileBackend(tmp_path, prefix_length=0)


def test_init_rejects_prefix_mismatch_on_multi_bag_layout(tmp_path):
    pytest.importorskip("bagofholding")
    s = BagOfHoldingH5FileBackend(tmp_path, prefix_length=2)
    s.put("value", _digest_like("a"))

    with pytest.raises(ValueError, match="prefix_length"):
        BagOfHoldingH5FileBackend(tmp_path, prefix_length=4)
    with pytest.raises(ValueError, match="prefix_length"):
        BagOfHoldingH5FileBackend(tmp_path)
    BagOfHoldingH5FileBackend(tmp_path, prefix_length=2)  # matching layout is fine


def test_init_rejects_prefix_on_per_key_layout(tmp_path):
    pytest.importorskip("bagofholding")
    s = BagOfHoldingH5FileBackend(tmp_path)
    s.put("value", _digest_like("a"))

    with pytest.raises(ValueError, match="prefix_length"):
        BagOfHoldingH5FileBackend(tmp_path, prefix_length=2)
    BagOfHoldingH5FileBackend(tmp_path)  # matching layout is fine


def test_init_check_ignores_unrelated_files(tmp_path):
    pytest.importorskip("bagofholding")
    (tmp_path / "notes.txt").write_text("not fleche's")
    (tmp_path / ".hidden").write_text("not fleche's")
    (tmp_path / "ab.h5.lock").write_text("")

    BagOfHoldingH5FileBackend(tmp_path)
    BagOfHoldingH5FileBackend(tmp_path, prefix_length=2)


def test_multi_bag_rebag(tmp_path):
    pytest.importorskip("bagofholding")
    s = BagOfHoldingH5FileBackend(tmp_path, prefix_length=2)
    key1 = Digest("ab" + "1" * 62)
    key2 = Digest("ab" + "2" * 62)
    s.put("first", key1)
    s.put("second", key2)

    s.rebag(version_validator="none")

    assert s.get(key1) == "first"
    assert s.get(key2) == "second"
