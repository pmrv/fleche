
import pytest
from fleche.call import Call
from fleche.digest import Digest
import fleche.digest as _fd
from fleche.caches import Cache


def _flip_last_nibble(hexstr: str) -> str:
    # Ensure we always change the digest but keep length and hex charset
    last = hexstr[-1]
    # simple alternating map to keep it deterministic
    table = {
        "0": "1",
        "1": "0",
        "2": "3",
        "3": "2",
        "4": "5",
        "5": "4",
        "6": "7",
        "7": "6",
        "8": "9",
        "9": "8",
        "a": "b",
        "b": "a",
        "c": "d",
        "d": "c",
        "e": "f",
        "f": "e",
    }
    return hexstr[:-1] + table[last]


def make_patched_digest(orig_digest, mode: str):
    """
    Build a single-site patched digest function with two modes:

    - "calls_change": Only Call hashing is altered; value hashing remains original.
    - "values_change_only": Call hashing remains as original (stable), but hashing of non-Call values changes.

    The wrapper preserves Digest identity by returning Digest values unchanged.
    """
    in_call_ctx = {"active": False}

    def patched(value):
        # Preserve identity of Digest tokens
        if isinstance(value, Digest):
            return value

        # Import lazily to avoid circulars during collection
        from fleche.call import Call as _Call

        if mode == "calls_change":
            if isinstance(value, _Call):
                d = orig_digest(value)
                return Digest(_flip_last_nibble(d))
            # non-Call values unchanged
            return orig_digest(value)

        if mode == "values_change_only":
            # Keep Call hashing stable by computing it purely with the original digest;
            # while hashing a Call, nested value hashing should also use original (guard by flag).
            if isinstance(value, _Call):
                was_active = in_call_ctx["active"]
                in_call_ctx["active"] = True
                try:
                    return orig_digest(value)
                finally:
                    in_call_ctx["active"] = was_active

            # Outside Call hashing, change value digests. While inside a Call hashing, stay original.
            if in_call_ctx["active"]:
                return orig_digest(value)
            d = orig_digest(value)
            return Digest(_flip_last_nibble(d))

        # Fallback: no change
        return orig_digest(value)

    return patched


@pytest.fixture
def sample_call():
    return Call(
        name="f",
        arguments={
            "a": [1, 2, (3, 4)],
            "b": {"k": 10},
        },
        metadata={},
        module=None,
        version=None,
        result=("x", {"y": 5}),
    )


def test_redigest_updates_call_keys_on_call_hash_change(monkeypatch, clean_cache, sample_call):
    original = sample_call

    key_before = clean_cache.save(original)
    set(clean_cache.calls.list())
    values_before = set(clean_cache.values.list())

    # Single-site patch: only Calls change
    import fleche.digest as fd

    patched = make_patched_digest(fd.digest, mode="calls_change")
    monkeypatch.setattr(fd, "digest", patched, raising=True)

    clean_cache.redigest()

    calls_after = set(clean_cache.calls.list())
    values_after = set(clean_cache.values.list())

    # Call key must change
    assert key_before not in calls_after
    # Compute expected new key under patched digest
    expected_key = original.to_lookup_key()
    assert expected_key in calls_after

    # Values remain unchanged
    assert values_after == values_before

    # Loading by new key succeeds and decodes structures
    loaded = clean_cache.load(expected_key)
    assert loaded.arguments["a"] == [1, 2, (3, 4)]
    assert loaded.arguments["b"] == {"k": 10}
    assert loaded.result == ("x", {"y": 5})


def test_redigest_noop_if_digest_unchanged(clean_cache, sample_call):
    original = sample_call

    key_before = clean_cache.save(original)
    calls_before = set(clean_cache.calls.list())
    values_before = set(clean_cache.values.list())

    clean_cache.redigest()

    calls_after = set(clean_cache.calls.list())
    values_after = set(clean_cache.values.list())

    assert calls_after == calls_before
    assert values_after == values_before

    loaded = clean_cache.load(key_before)
    assert loaded.arguments["a"] == [1, 2, (3, 4)]
    assert loaded.arguments["b"] == {"k": 10}
    assert loaded.result == ("x", {"y": 5})


def test_redigest_orphans_value_keys_when_one_type_changes(monkeypatch, clean_cache, sample_call):
    """When only one type's hash changes, redigest re-keys calls but orphans old value entries.

    Simulates a scenario like "int hashing gained a version prefix". Calls containing
    int arguments get new lookup keys; redigest re-saves them under those new keys and
    stores new value entries. The old value entries (saved before the change) are left
    behind as orphans — only a subsequent gc() removes them.
    """
    original = sample_call

    key_before = clean_cache.save(original)
    values_before = set(clean_cache.values.list())

    orig_digest_bytes = _fd._digest_bytes

    def patched_int_only(value):
        # Change int hashing by flipping the last nibble of the resulting hex digest.
        # bool is a subclass of int but treated as a separate logical type; leave it unchanged.
        if type(value) is int:
            raw = orig_digest_bytes(value)
            return _flip_last_nibble(raw.decode()).encode()
        return orig_digest_bytes(value)

    monkeypatch.setattr(_fd, "_digest_bytes", patched_int_only)

    clean_cache.redigest()

    calls_after = set(clean_cache.calls.list())
    values_after = set(clean_cache.values.list())

    # Call key changes because arguments contain ints.
    assert key_before not in calls_after
    new_key = original.to_lookup_key()
    assert new_key in calls_after

    # redigest() does NOT evict old value entries — they become orphans.
    assert values_before <= values_after
    # New value entries were added under the new int-derived keys.
    assert values_after > values_before

    # Loading by the new key round-trips correctly.
    loaded = clean_cache.load(new_key).fetch()
    assert loaded.arguments["a"] == [1, 2, (3, 4)]
    assert loaded.arguments["b"] == {"k": 10}
    assert loaded.result == ("x", {"y": 5})


def test_redigest_orphans_all_value_keys_when_entire_hash_changes(monkeypatch, clean_cache, sample_call):
    """When the hash function changes for all types, every old value entry is orphaned.

    Simulates switching the underlying hash primitive (e.g. SHA-256 → blake2b).
    redigest() re-saves all calls and their values under the new keys but never touches
    old value entries, leaving the entire pre-migration value set as orphans.  A
    subsequent gc() must clean them all up.
    """
    import hashlib

    original = sample_call

    key_before = clean_cache.save(original)
    values_before = set(clean_cache.values.list())

    # Replace the hash primitive inside digest.py with blake2b(digest_size=32).
    # blake2b produces 32-byte (64 hex-char) digests, so the output format is
    # identical to sha256 and all downstream code continues to work.  This is a
    # clean simulation of "the entire hash function was swapped": every digest
    # changes, the Digest passthrough invariant is preserved, and Call / DigestedCall
    # to_lookup_key() remain consistent with each other.
    class _Blake2bHashlib:
        @staticmethod
        def sha256():
            return hashlib.blake2b(digest_size=32)

    monkeypatch.setattr(_fd, "hashlib", _Blake2bHashlib)

    clean_cache.redigest()

    calls_after = set(clean_cache.calls.list())
    values_after = set(clean_cache.values.list())

    # All call keys change; the one call is re-keyed.
    assert key_before not in calls_after
    new_key = original.to_lookup_key()
    assert new_key in calls_after

    # redigest() leaves all old value entries in place (orphaned).
    assert values_before <= values_after
    assert values_after > values_before

    # Loading by the new key round-trips correctly.
    loaded = clean_cache.load(new_key).fetch()
    assert loaded.arguments["a"] == [1, 2, (3, 4)]
    assert loaded.arguments["b"] == {"k": 10}
    assert loaded.result == ("x", {"y": 5})


def _patch_int_digest(monkeypatch):
    """Flip the last nibble of every int's digest, leaving all other types alone."""
    orig_digest_bytes = _fd._digest_bytes

    def patched(value):
        if type(value) is int:
            raw = orig_digest_bytes(value)
            return _flip_last_nibble(raw.decode()).encode()
        return orig_digest_bytes(value)

    monkeypatch.setattr(_fd, "_digest_bytes", patched)


def test_redigest_multi_call_only_changed_call_is_touched(monkeypatch, clean_cache):
    """A multi-call cache: only calls whose key actually changes are re-saved/evicted."""
    call_int = Call(name="f", arguments={"a": 1}, metadata={}, module=None, version=None, result="r1")
    call_str = Call(name="f", arguments={"a": "x"}, metadata={}, module=None, version=None, result="r2")

    key_int_before = clean_cache.save(call_int)
    key_str_before = clean_cache.save(call_str)

    _patch_int_digest(monkeypatch)

    evicted = []
    orig_evict = Cache.evict

    def spy_evict(self, key):
        evicted.append(key)
        return orig_evict(self, key)

    monkeypatch.setattr(Cache, "evict", spy_evict)

    clean_cache.redigest()

    calls_after = set(clean_cache.calls.list())

    # The call with an int argument is re-keyed ...
    new_key_int = call_int.to_lookup_key()
    assert key_int_before not in calls_after
    assert new_key_int in calls_after
    assert key_int_before in evicted

    # ... while the call with no int arguments keeps its original key and is
    # never evicted/re-saved.
    assert call_str.to_lookup_key() == key_str_before
    assert key_str_before in calls_after
    assert key_str_before not in evicted

    assert clean_cache.load(new_key_int).fetch().result == "r1"
    assert clean_cache.load(key_str_before).fetch().result == "r2"


def test_redigest_second_call_is_noop(monkeypatch, clean_cache, sample_call):
    """Calling redigest() again once keys are consistent does nothing."""
    original = sample_call
    clean_cache.save(original)

    _patch_int_digest(monkeypatch)

    clean_cache.redigest()
    calls_after_first = set(clean_cache.calls.list())
    values_after_first = set(clean_cache.values.list())

    evicted = []
    saved = []
    orig_evict = Cache.evict
    orig_save = Cache.save

    def spy_evict(self, key):
        evicted.append(key)
        return orig_evict(self, key)

    def spy_save(self, call):
        saved.append(call)
        return orig_save(self, call)

    monkeypatch.setattr(Cache, "evict", spy_evict)
    monkeypatch.setattr(Cache, "save", spy_save)

    clean_cache.redigest()

    assert not evicted
    assert not saved
    assert set(clean_cache.calls.list()) == calls_after_first
    assert set(clean_cache.values.list()) == values_after_first


def test_redigest_propagates_load_error_leaving_partial_migration(monkeypatch, clean_cache):
    """redigest() bails out on the first load/fetch error instead of skipping it.

    Documents the current behaviour (#618 gap 4): calls processed before the
    failing one are already migrated, the failing call and everything after it
    in iteration order are left untouched, and the exception propagates to the
    caller instead of being swallowed.
    """
    call_first = Call(name="f", arguments={"a": 1}, metadata={}, module=None, version=None, result="r1")
    call_second = Call(name="f", arguments={"a": 2}, metadata={}, module=None, version=None, result="r2")

    key_first_before = clean_cache.save(call_first)
    key_second_before = clean_cache.save(call_second)

    _patch_int_digest(monkeypatch)

    orig_load = Cache.load

    def failing_load(self, key):
        if key == key_second_before:
            raise RuntimeError("boom")
        return orig_load(self, key)

    monkeypatch.setattr(Cache, "load", failing_load)

    with pytest.raises(RuntimeError, match="boom"):
        clean_cache.redigest()

    calls_after = set(clean_cache.calls.list())

    # The first call, processed before the failure, was migrated ...
    new_key_first = call_first.to_lookup_key()
    assert key_first_before not in calls_after
    assert new_key_first in calls_after

    # ... but the second call was never reached and is left under its old key.
    assert key_second_before in calls_after


def test_redigest_on_file_backed_cache(monkeypatch, file_cache, sample_call):
    """redigest() migrates keys correctly on a disk-backed cache, not just in-memory."""
    original = sample_call

    key_before = file_cache.save(original)

    import fleche.digest as fd

    patched = make_patched_digest(fd.digest, mode="calls_change")
    monkeypatch.setattr(fd, "digest", patched, raising=True)

    file_cache.redigest()

    calls_after = set(file_cache.calls.list())
    assert key_before not in calls_after
    expected_key = original.to_lookup_key()
    assert expected_key in calls_after

    loaded = file_cache.load(expected_key).fetch()
    assert loaded.arguments["a"] == [1, 2, (3, 4)]
    assert loaded.arguments["b"] == {"k": 10}
    assert loaded.result == ("x", {"y": 5})
