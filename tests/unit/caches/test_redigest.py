
import pytest
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


def test_redigest_multi_call_only_changed_keys_are_resaved(monkeypatch, clean_cache):
    """Gap 2: a multi-call cache where only some calls' keys change.

    Unchanged calls must be left completely untouched — not merely present
    under the same key, but never re-saved at all.  We pin this by tracking
    object identity of the underlying storage records: ``redigest()`` must
    ``continue`` on an unchanged key rather than resave an equal copy, so the
    stored object for that key must be the exact same object afterwards.
    """
    unchanged_call = Call(
        name="unchanged", arguments={"x": 1}, metadata={}, module=None, version=None, result="a",
    )
    changed_call = Call(
        name="changed", arguments={"x": 2}, metadata={}, module=None, version=None, result="b",
    )

    unchanged_key = clean_cache.save(unchanged_call)
    changed_key = clean_cache.save(changed_call)

    import fleche.digest as fd
    orig_digest = fd.digest

    def patched(value):
        if isinstance(value, Digest):
            return value
        if isinstance(value, Call) and value.name == "changed":
            d = orig_digest(value)
            return Digest(_flip_last_nibble(d))
        return orig_digest(value)

    monkeypatch.setattr(fd, "digest", patched, raising=True)

    unchanged_record_id_before = id(clean_cache.calls.storage[unchanged_key])

    clean_cache.redigest()

    calls_after = set(clean_cache.calls.list())
    new_changed_key = changed_call.to_lookup_key()

    # The changed call is re-keyed.
    assert changed_key not in calls_after
    assert new_changed_key in calls_after

    # The unchanged call's key and its underlying storage record are
    # completely untouched.
    assert unchanged_key in calls_after
    assert id(clean_cache.calls.storage[unchanged_key]) == unchanged_record_id_before

    loaded_unchanged = clean_cache.load(unchanged_key).fetch()
    assert loaded_unchanged.result == "a"
    loaded_changed = clean_cache.load(new_changed_key).fetch()
    assert loaded_changed.result == "b"


def test_redigest_idempotent_second_run_is_noop(monkeypatch, clean_cache, sample_call):
    """Gap 3: calling redigest() again once keys are consistent is a no-op.

    No re-saves and no evictions should happen on the second call — pinned
    via object identity of every stored record, not just key-set equality.
    """
    original = sample_call
    clean_cache.save(original)

    import fleche.digest as fd
    patched = make_patched_digest(fd.digest, mode="calls_change")
    monkeypatch.setattr(fd, "digest", patched, raising=True)

    clean_cache.redigest()

    calls_after_first = set(clean_cache.calls.list())
    values_after_first = set(clean_cache.values.list())
    call_record_ids = {k: id(v) for k, v in clean_cache.calls.storage.items()}
    value_record_ids = {k: id(v) for k, v in clean_cache.values.storage.items()}

    clean_cache.redigest()

    assert set(clean_cache.calls.list()) == calls_after_first
    assert set(clean_cache.values.list()) == values_after_first
    for k, v in clean_cache.calls.storage.items():
        assert id(v) == call_record_ids[k]
    for k, v in clean_cache.values.storage.items():
        assert id(v) == value_record_ids[k]


def test_redigest_converges_after_simulated_partial_migration(monkeypatch, clean_cache):
    """Gap 3 (partial-interruption recovery, #451): a second run converges.

    redigest() migrates calls one at a time and is not itself transactional
    across the whole loop, so an interruption between iterations (e.g. a
    killed process) can leave some calls already re-keyed and others still on
    their old key. This simulates that state directly (rather than actually
    killing the process) and checks a subsequent redigest() run finishes the
    migration and reaches the same end state as an uninterrupted run.
    """
    calls = [
        Call(name=f"f{i}", arguments={"x": i}, metadata={}, module=None, version=None, result=i)
        for i in range(3)
    ]
    keys_before = [clean_cache.save(c) for c in calls]

    import fleche.digest as fd
    patched = make_patched_digest(fd.digest, mode="calls_change")
    monkeypatch.setattr(fd, "digest", patched, raising=True)

    new_keys = [c.to_lookup_key() for c in calls]

    # Simulate a first pass that migrated only the first call before being
    # interrupted.
    clean_cache.save(calls[0])
    clean_cache.evict(keys_before[0])

    partial_calls = set(clean_cache.calls.list())
    assert new_keys[0] in partial_calls
    assert keys_before[1] in partial_calls
    assert keys_before[2] in partial_calls

    # A (here, first *actual*) redigest() run must finish the migration.
    clean_cache.redigest()

    calls_after = set(clean_cache.calls.list())
    assert calls_after == set(new_keys)
    for c, k in zip(calls, new_keys):
        loaded = clean_cache.load(k).fetch()
        assert loaded.result == c.result

    # Running it again is a no-op (full idempotency after recovery).
    record_ids = {k: id(v) for k, v in clean_cache.calls.storage.items()}
    clean_cache.redigest()
    for k, v in clean_cache.calls.storage.items():
        assert id(v) == record_ids[k]


def _make_broken_call(clean_cache, name: str):
    """Save a call and then corrupt its result's value entry.

    Deletes the result's entry directly from the value storage dict so a
    later ``load(key).fetch()`` raises ``KeyError`` — simulating a corrupt or
    partially-evicted cache without needing to monkeypatch any frozen cache
    object's methods.
    """
    from fleche.digest import digest as digest_fn

    result = f"result-of-{name}"
    call = Call(name=name, arguments={}, metadata={}, module=None, version=None, result=result)
    key = clean_cache.save(call)
    value_key = digest_fn(result)
    del clean_cache.values.storage[value_key]
    return call, key


def test_redigest_onerror_raise_default_propagates_and_leaves_state_partial(monkeypatch, clean_cache):
    """Gap 4: the default onerror='raise' propagates and bails out of the loop.

    A good call earlier in iteration order is already migrated by the time
    the broken one raises; the exception then propagates to the caller
    exactly as documented, leaving the cache partially migrated.
    """
    good_call = Call(name="good", arguments={"x": 1}, metadata={}, module=None, version=None, result=1)
    good_key = clean_cache.save(good_call)
    bad_call, bad_key = _make_broken_call(clean_cache, "bad")

    import fleche.digest as fd
    patched = make_patched_digest(fd.digest, mode="calls_change")
    monkeypatch.setattr(fd, "digest", patched, raising=True)

    with pytest.raises(KeyError):
        clean_cache.redigest()

    # The good call (processed first) is already migrated.
    new_good_key = good_call.to_lookup_key()
    calls_after = set(clean_cache.calls.list())
    assert good_key not in calls_after
    assert new_good_key in calls_after

    # The broken call is left in place, still corrupt.
    assert bad_key in calls_after


def test_redigest_onerror_skip_continues_and_leaves_entry_untouched(monkeypatch, clean_cache, caplog):
    """Gap 4: onerror='skip' logs a warning and leaves the broken entry as-is."""
    good_call = Call(name="good", arguments={"x": 1}, metadata={}, module=None, version=None, result=1)
    good_key = clean_cache.save(good_call)
    bad_call, bad_key = _make_broken_call(clean_cache, "bad")

    import fleche.digest as fd
    patched = make_patched_digest(fd.digest, mode="calls_change")
    monkeypatch.setattr(fd, "digest", patched, raising=True)

    with caplog.at_level("WARNING", logger="fleche.cache"):
        clean_cache.redigest(onerror="skip")

    new_good_key = good_call.to_lookup_key()
    calls_after = set(clean_cache.calls.list())
    assert good_key not in calls_after
    assert new_good_key in calls_after

    # Broken entry is untouched (still present under its original key).
    assert bad_key in calls_after
    assert any("skipping" in rec.message for rec in caplog.records)


def test_redigest_onerror_evict_continues_and_evicts_broken_entry(monkeypatch, clean_cache, caplog):
    """Gap 4: onerror='evict' logs a warning and evicts the broken entry."""
    good_call = Call(name="good", arguments={"x": 1}, metadata={}, module=None, version=None, result=1)
    good_key = clean_cache.save(good_call)
    bad_call, bad_key = _make_broken_call(clean_cache, "bad")

    import fleche.digest as fd
    patched = make_patched_digest(fd.digest, mode="calls_change")
    monkeypatch.setattr(fd, "digest", patched, raising=True)

    with caplog.at_level("WARNING", logger="fleche.cache"):
        clean_cache.redigest(onerror="evict")

    new_good_key = good_call.to_lookup_key()
    calls_after = set(clean_cache.calls.list())
    assert good_key not in calls_after
    assert new_good_key in calls_after

    # Broken entry is gone entirely.
    assert bad_key not in calls_after
    assert not clean_cache.contains(bad_key)
    assert any("evicting" in rec.message for rec in caplog.records)


def test_redigest_invalid_onerror_raises_value_error(clean_cache):
    with pytest.raises(ValueError):
        clean_cache.redigest(onerror="bogus")


def test_redigest_file_backed_cache_updates_keys_on_disk(monkeypatch, file_cache, sample_call):
    """Gap 5: redigest() also works against a disk-backed (file) cache."""
    original = sample_call
    key_before = file_cache.save(original)
    assert file_cache.calls._path(key_before).exists()

    import fleche.digest as fd
    patched = make_patched_digest(fd.digest, mode="calls_change")
    monkeypatch.setattr(fd, "digest", patched, raising=True)

    file_cache.redigest()

    new_key = original.to_lookup_key()
    assert new_key != key_before
    assert not file_cache.calls._path(key_before).exists()
    assert file_cache.calls._path(new_key).exists()

    loaded = file_cache.load(new_key).fetch()
    assert loaded.arguments["a"] == [1, 2, (3, 4)]
    assert loaded.arguments["b"] == {"k": 10}
    assert loaded.result == ("x", {"y": 5})

    # Idempotent on a file-backed cache too: a second run touches nothing.
    mtime_before = file_cache.calls._path(new_key).stat().st_mtime_ns
    file_cache.redigest()
    assert file_cache.calls._path(new_key).stat().st_mtime_ns == mtime_before


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
