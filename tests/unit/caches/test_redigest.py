
import pytest
from fleche.storage import ValueMemory, CallMemory
from fleche.caches import Cache
from fleche.call import Call
from fleche.digest import Digest
import fleche.digest as _fd


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
def cache():
    return Cache(ValueMemory({}), CallMemory({}))


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


def test_redigest_updates_call_keys_on_call_hash_change(monkeypatch, cache, sample_call):
    original = sample_call

    key_before = cache.save(original)
    set(cache.calls.list())
    values_before = set(cache.values.list())

    # Single-site patch: only Calls change
    import fleche.digest as fd

    patched = make_patched_digest(fd.digest, mode="calls_change")
    monkeypatch.setattr(fd, "digest", patched, raising=True)

    cache.redigest()

    calls_after = set(cache.calls.list())
    values_after = set(cache.values.list())

    # Call key must change
    assert key_before not in calls_after
    # Compute expected new key under patched digest
    expected_key = original.to_lookup_key()
    assert expected_key in calls_after

    # Values remain unchanged
    assert values_after == values_before

    # Loading by new key succeeds and decodes structures
    loaded = cache.load(expected_key)
    assert loaded.arguments["a"] == [1, 2, (3, 4)]
    assert loaded.arguments["b"] == {"k": 10}
    assert loaded.result == ("x", {"y": 5})


def test_redigest_noop_if_digest_unchanged(cache, sample_call):
    original = sample_call

    key_before = cache.save(original)
    calls_before = set(cache.calls.list())
    values_before = set(cache.values.list())

    cache.redigest()

    calls_after = set(cache.calls.list())
    values_after = set(cache.values.list())

    assert calls_after == calls_before
    assert values_after == values_before

    loaded = cache.load(key_before)
    assert loaded.arguments["a"] == [1, 2, (3, 4)]
    assert loaded.arguments["b"] == {"k": 10}
    assert loaded.result == ("x", {"y": 5})


def test_redigest_orphans_value_keys_when_one_type_changes(monkeypatch, cache, sample_call):
    """When only one type's hash changes, redigest re-keys calls but orphans old value entries.

    Simulates a scenario like "int hashing gained a version prefix". Calls containing
    int arguments get new lookup keys; redigest re-saves them under those new keys and
    stores new value entries. The old value entries (saved before the change) are left
    behind as orphans — only a subsequent gc() removes them.
    """
    original = sample_call

    key_before = cache.save(original)
    values_before = set(cache.values.list())

    orig_digest_bytes = _fd._digest_bytes

    def patched_int_only(value):
        # Change int hashing by flipping the last nibble of the resulting hex digest.
        # bool is a subclass of int but treated as a separate logical type; leave it unchanged.
        if type(value) is int:
            raw = orig_digest_bytes(value)
            return _flip_last_nibble(raw.decode()).encode()
        return orig_digest_bytes(value)

    monkeypatch.setattr(_fd, "_digest_bytes", patched_int_only)

    cache.redigest()

    calls_after = set(cache.calls.list())
    values_after = set(cache.values.list())

    # Call key changes because arguments contain ints.
    assert key_before not in calls_after
    new_key = original.to_lookup_key()
    assert new_key in calls_after

    # redigest() does NOT evict old value entries — they become orphans.
    assert values_before <= values_after
    # New value entries were added under the new int-derived keys.
    assert values_after > values_before

    # Loading by the new key round-trips correctly.
    loaded = cache.load(new_key).fetch()
    assert loaded.arguments["a"] == [1, 2, (3, 4)]
    assert loaded.arguments["b"] == {"k": 10}
    assert loaded.result == ("x", {"y": 5})


def test_redigest_orphans_all_value_keys_when_entire_hash_changes(monkeypatch, cache, sample_call):
    """When the hash function changes for all types, every old value entry is orphaned.

    Simulates switching the underlying hash primitive (e.g. SHA-256 → blake2b).
    redigest() re-saves all calls and their values under the new keys but never touches
    old value entries, leaving the entire pre-migration value set as orphans.  A
    subsequent gc() must clean them all up.
    """
    import hashlib

    original = sample_call

    key_before = cache.save(original)
    values_before = set(cache.values.list())

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

    cache.redigest()

    calls_after = set(cache.calls.list())
    values_after = set(cache.values.list())

    # All call keys change; the one call is re-keyed.
    assert key_before not in calls_after
    new_key = original.to_lookup_key()
    assert new_key in calls_after

    # redigest() leaves all old value entries in place (orphaned).
    assert values_before <= values_after
    assert values_after > values_before

    # Loading by the new key round-trips correctly.
    loaded = cache.load(new_key).fetch()
    assert loaded.arguments["a"] == [1, 2, (3, 4)]
    assert loaded.arguments["b"] == {"k": 10}
    assert loaded.result == ("x", {"y": 5})
