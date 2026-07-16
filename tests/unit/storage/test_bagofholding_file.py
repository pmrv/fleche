import logging
from unittest.mock import MagicMock

import pytest

from fleche.digest import Digest
from fleche.storage.bagofholding_file import BagOfHoldingH5FileBackend


def test_load_corrupt_h5_file(tmp_path, caplog):
    storage = BagOfHoldingH5FileBackend(tmp_path, prefix_length=0)

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


def test_prefix_length_default_is_2(tmp_path):
    pytest.importorskip("bagofholding")
    s = BagOfHoldingH5FileBackend(tmp_path)
    assert s.prefix_length == 2


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

    s = BagOfHoldingH5FileBackend(tmp_path, prefix_length=0)
    key = Digest("a" * 64)
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

    s = BagOfHoldingH5FileBackend(tmp_path, prefix_length=0)
    key = Digest("b" * 64)
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

    s = BagOfHoldingH5FileBackend(tmp_path, prefix_length=0)
    key = Digest("c" * 64)
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

    s = BagOfHoldingH5FileBackend(tmp_path, prefix_length=0)
    key = Digest("d" * 64)
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
    import h5py

    s = BagOfHoldingH5FileBackend(tmp_path, prefix_length=0)
    keys = [
        Digest("ab" + "1" * 62),
        Digest("ab" + "2" * 62),
        Digest("cd" + "3" * 62),
        Digest("cd" + "4" * 62),
    ]
    for i, key in enumerate(keys):
        s.put(f"value{i}", key)

    s.refix(2)

    assert s.prefix_length == 2
    assert {p.name for p in tmp_path.glob("*.h5")} == {"ab.h5", "cd.h5"}
    for key in keys:
        assert not (tmp_path / key).exists()
    with h5py.File(tmp_path / "ab.h5", "r") as f:
        assert set(f.keys()) == {keys[0], keys[1]}  # siblings share one file
    for i, key in enumerate(keys):
        assert s.get(key) == f"value{i}"


def test_refix_to_per_key(tmp_path):
    pytest.importorskip("bagofholding")
    s = BagOfHoldingH5FileBackend(tmp_path, prefix_length=2)
    keys = [
        Digest("ab" + "1" * 62),
        Digest("ab" + "2" * 62),
        Digest("cd" + "3" * 62),
    ]
    for i, key in enumerate(keys):
        s.put(f"value{i}", key)

    s.refix(0)

    assert s.prefix_length == 0
    assert not list(tmp_path.glob("*.h5"))
    for i, key in enumerate(keys):
        assert (tmp_path / key).is_file()
        assert s.get(key) == f"value{i}"


def test_refix_splits_bags(tmp_path):
    pytest.importorskip("bagofholding")
    import h5py

    s = BagOfHoldingH5FileBackend(tmp_path, prefix_length=2)
    keys = [
        Digest("ab11" + "1" * 60),
        Digest("ab11" + "2" * 60),
        Digest("ab22" + "3" * 60),
    ]
    for i, key in enumerate(keys):
        s.put(f"value{i}", key)
    assert {p.name for p in tmp_path.glob("*.h5")} == {"ab.h5"}

    s.refix(4)

    assert {p.name for p in tmp_path.glob("*.h5")} == {"ab11.h5", "ab22.h5"}
    with h5py.File(tmp_path / "ab11.h5", "r") as f:
        assert set(f.keys()) == {keys[0], keys[1]}
    for i, key in enumerate(keys):
        assert s.get(key) == f"value{i}"


def test_refix_merges_bags(tmp_path):
    pytest.importorskip("bagofholding")
    import h5py

    s = BagOfHoldingH5FileBackend(tmp_path, prefix_length=4)
    keys = [
        Digest("ab11" + "1" * 60),
        Digest("ab22" + "2" * 60),
        Digest("cd11" + "3" * 60),
    ]
    for i, key in enumerate(keys):
        s.put(f"value{i}", key)
    assert len(list(tmp_path.glob("*.h5"))) == 3

    s.refix(2)

    assert {p.name for p in tmp_path.glob("*.h5")} == {"ab.h5", "cd.h5"}
    with h5py.File(tmp_path / "ab.h5", "r") as f:
        assert set(f.keys()) == {keys[0], keys[1]}  # merged into one file
    for i, key in enumerate(keys):
        assert s.get(key) == f"value{i}"


def test_refix_noop_does_not_touch_filesystem(tmp_path, monkeypatch):
    pytest.importorskip("bagofholding")
    import fleche.storage.bagofholding_file as boh_mod

    s = BagOfHoldingH5FileBackend(tmp_path, prefix_length=2)
    key1 = s.put("first")
    key2 = s.put("second")
    before = sorted((p.name, p.stat().st_mtime_ns, p.stat().st_size) for p in tmp_path.iterdir())

    saves = []
    monkeypatch.setattr(
        boh_mod.H5Bag, "save", staticmethod(lambda value, path: saves.append(path))
    )

    s.refix(2)

    assert not saves
    after = sorted((p.name, p.stat().st_mtime_ns, p.stat().st_size) for p in tmp_path.iterdir())
    assert after == before
    assert s.get(key1) == "first"
    assert s.get(key2) == "second"


def test_refix_unlinks_old_bags_as_soon_as_drained(tmp_path, monkeypatch):
    """Each old bag must be gone before the next one\'s entries are copied,
    so disk usage never balloons beyond one bag\'s worth of duplicates."""
    pytest.importorskip("bagofholding")
    import fleche.storage.bagofholding_file as boh_mod
    from pathlib import Path

    s = BagOfHoldingH5FileBackend(tmp_path, prefix_length=2)
    key1 = Digest("ab" + "1" * 62)
    key2 = Digest("ab" + "2" * 62)
    key3 = Digest("cd" + "3" * 62)
    s.put("first", key1)
    s.put("second", key2)
    s.put("third", key3)

    real_save = boh_mod.H5Bag.save
    bags_at_save = {}

    def spying_save(value, path):
        bags_at_save[Path(path).name] = {p.name for p in tmp_path.glob("*.h5")}
        return real_save(value, path)

    monkeypatch.setattr(boh_mod.H5Bag, "save", staticmethod(spying_save))

    s.refix(4)

    # bags are drained in sorted order, so ab.h5 must already be unlinked by
    # the time cd.h5\'s entry is copied into the new layout
    assert "ab.h5" not in bags_at_save[str(key3)]
    for key, value in ((key1, "first"), (key2, "second"), (key3, "third")):
        assert s.get(key) == value


def test_refix_raises_on_unreadable_entry(tmp_path, monkeypatch):
    """Silently skipping an unreadable entry would leave a mixed root whose
    *next* instantiation fails, so refix must alert the user immediately."""
    pytest.importorskip("bagofholding")
    import h5py

    s = BagOfHoldingH5FileBackend(tmp_path, prefix_length=2)
    key1 = Digest("ab" + "1" * 62)
    key2 = Digest("ab" + "2" * 62)
    s.put("first", key1)
    s.put("second", key2)

    real_from_file = BagOfHoldingH5FileBackend._from_file

    def failing_from_file(self, path):
        if path.name == key2:
            raise KeyError(path)
        return real_from_file(self, path)

    monkeypatch.setattr(BagOfHoldingH5FileBackend, "_from_file", failing_from_file)

    with pytest.raises(RuntimeError, match="consolidate"):
        s.refix(0)

    # nothing was dropped from the old bag, the readable entry was copied
    with h5py.File(tmp_path / "ab.h5", "r") as f:
        assert set(f.keys()) == {key1, key2}
    assert (tmp_path / key1).is_file()


def test_refix_rejects_unspecific_or_invalid_target(tmp_path):
    pytest.importorskip("bagofholding")
    s = BagOfHoldingH5FileBackend(tmp_path)
    for bad in (None, -1, 65):
        with pytest.raises(ValueError, match="prefix_length"):
            s.refix(bad)


def test_reopen_after_refix(tmp_path):
    pytest.importorskip("bagofholding")
    s = BagOfHoldingH5FileBackend(tmp_path, prefix_length=0)
    key1 = s.put("first")
    key2 = s.put("second")

    s.refix(2)

    reopened = BagOfHoldingH5FileBackend(tmp_path, prefix_length=2)
    assert reopened.get(key1) == "first"
    assert reopened.get(key2) == "second"


def _mixed_root(tmp_path):
    """A root holding two layouts at once: two keys in ab.h5 plus one per-key file."""
    s2 = BagOfHoldingH5FileBackend(tmp_path, prefix_length=2)
    key1 = Digest("ab" + "1" * 62)
    key2 = Digest("ab" + "2" * 62)
    s2.put("first", key1)
    s2.put("second", key2)
    s0 = BagOfHoldingH5FileBackend(tmp_path, prefix_length=0, check_consistency=False)
    key3 = Digest("ef" + "3" * 62)
    s0.put("third", key3)
    return key1, key2, key3


def test_consolidate_repairs_mixed_root(tmp_path):
    pytest.importorskip("bagofholding")
    import h5py

    key1, key2, key3 = _mixed_root(tmp_path)
    # a mixed root cannot be opened normally with either prefix length
    with pytest.raises(ValueError, match="prefix_length"):
        BagOfHoldingH5FileBackend(tmp_path, prefix_length=2)
    with pytest.raises(ValueError, match="prefix_length"):
        BagOfHoldingH5FileBackend(tmp_path, prefix_length=0)

    s = BagOfHoldingH5FileBackend.consolidate(tmp_path, prefix_length=2)

    assert s.prefix_length == 2
    assert {p.name for p in tmp_path.glob("*.h5")} == {"ab.h5", "ef.h5"}
    assert not (tmp_path / key3).exists()
    with h5py.File(tmp_path / "ab.h5", "r") as f:
        assert set(f.keys()) == {key1, key2}
    for key, value in ((key1, "first"), (key2, "second"), (key3, "third")):
        assert s.get(key) == value


def test_consolidate_on_uniform_root(tmp_path):
    pytest.importorskip("bagofholding")
    s2 = BagOfHoldingH5FileBackend(tmp_path, prefix_length=2)
    key1 = s2.put("first")
    key2 = s2.put("second")

    s = BagOfHoldingH5FileBackend.consolidate(tmp_path, prefix_length=4)

    assert s.prefix_length == 4
    assert s.get(key1) == "first"
    assert s.get(key2) == "second"


def test_blind_instance_sees_only_its_own_layout(tmp_path):
    pytest.importorskip("bagofholding")
    key1, key2, key3 = _mixed_root(tmp_path)

    s2 = BagOfHoldingH5FileBackend(tmp_path, prefix_length=2, check_consistency=False)
    s0 = BagOfHoldingH5FileBackend(tmp_path, prefix_length=0, check_consistency=False)

    assert set(s2.list()) == {key1, key2}
    assert set(s0.list()) == {key3}
    assert not s2.contains(key3)
    assert not s0.contains(key1)


def test_check_consistency_false_requires_explicit_prefix(tmp_path):
    pytest.importorskip("bagofholding")
    with pytest.raises(ValueError, match="explicit prefix_length"):
        BagOfHoldingH5FileBackend(tmp_path, prefix_length=None, check_consistency=False)


def test_infer_prefix_length_from_existing_files(tmp_path):
    pytest.importorskip("bagofholding")
    s4 = BagOfHoldingH5FileBackend(tmp_path / "four", prefix_length=4)
    key = s4.put("value")
    s0 = BagOfHoldingH5FileBackend(tmp_path / "zero", prefix_length=0)
    key0 = s0.put("value")

    inferred4 = BagOfHoldingH5FileBackend(tmp_path / "four", prefix_length=None)
    inferred0 = BagOfHoldingH5FileBackend(tmp_path / "zero", prefix_length=None)

    assert inferred4.prefix_length == 4
    assert inferred4.get(key) == "value"
    assert inferred0.prefix_length == 0
    assert inferred0.get(key0) == "value"


def test_infer_prefix_length_empty_root_uses_default(tmp_path):
    pytest.importorskip("bagofholding")
    s = BagOfHoldingH5FileBackend(tmp_path, prefix_length=None)
    assert s.prefix_length == 2


def test_infer_prefix_length_mixed_root_raises(tmp_path):
    pytest.importorskip("bagofholding")
    _mixed_root(tmp_path)
    with pytest.raises(ValueError, match="consolidate"):
        BagOfHoldingH5FileBackend(tmp_path, prefix_length=None)


def test_init_rejects_invalid_prefix_length(tmp_path):
    pytest.importorskip("bagofholding")
    for bad in (-1, 65):
        with pytest.raises(ValueError, match="prefix_length"):
            BagOfHoldingH5FileBackend(tmp_path, prefix_length=bad)


def test_init_rejects_prefix_mismatch_on_multi_bag_layout(tmp_path):
    pytest.importorskip("bagofholding")
    s = BagOfHoldingH5FileBackend(tmp_path, prefix_length=2)
    s.put("first")
    s.put("second")

    with pytest.raises(ValueError, match="prefix_length"):
        BagOfHoldingH5FileBackend(tmp_path, prefix_length=4)
    with pytest.raises(ValueError, match="prefix_length"):
        BagOfHoldingH5FileBackend(tmp_path, prefix_length=0)
    BagOfHoldingH5FileBackend(tmp_path, prefix_length=2)  # matching layout is fine


def test_init_rejects_prefix_on_per_key_layout(tmp_path):
    pytest.importorskip("bagofholding")
    s = BagOfHoldingH5FileBackend(tmp_path, prefix_length=0)
    s.put("first")
    s.put("second")

    with pytest.raises(ValueError, match="prefix_length"):
        BagOfHoldingH5FileBackend(tmp_path, prefix_length=2)
    BagOfHoldingH5FileBackend(tmp_path, prefix_length=0)  # matching layout is fine


def test_init_check_ignores_unrelated_files(tmp_path):
    pytest.importorskip("bagofholding")
    (tmp_path / "notes.txt").write_text("not fleche\'s")
    (tmp_path / ".hidden").write_text("not fleche\'s")
    (tmp_path / "ab.h5.lock").write_text("")

    BagOfHoldingH5FileBackend(tmp_path, prefix_length=0)
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
