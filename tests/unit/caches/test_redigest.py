import pytest

from fleche.storage import Memory
from fleche.caches import Cache
from fleche.call import Call
from fleche.digest import Digest


def _flip_last_nibble(hexstr: str) -> str:
    # Ensure we always change the digest but keep length and hex charset
    last = hexstr[-1]
    # simple alternating map to keep it deterministic
    table = {
        "0": "1", "1": "0",
        "2": "3", "3": "2",
        "4": "5", "5": "4",
        "6": "7", "7": "6",
        "8": "9", "9": "8",
        "a": "b", "b": "a",
        "c": "d", "d": "c",
        "e": "f", "f": "e",
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


def _make_cache():
    values = Memory({})
    calls = Memory({})
    return Cache(values, calls)


def _sample_call():
    # Use nested args/result to ensure value storage involvement
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


def test_redigest_updates_call_keys_on_call_hash_change(monkeypatch):
    cache = _make_cache()
    original = _sample_call()

    key_before = cache.save(original)
    calls_before = set(cache.calls.list())
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


def test_redigest_noop_if_digest_unchanged(monkeypatch):
    cache = _make_cache()
    original = _sample_call()

    key_before = cache.save(original)
    calls_before = set(cache.calls.list())
    values_before = set(cache.values.list())

    import fleche.digest as fd

    def passthrough(v):
        return fd.digest.__wrapped__(v) if hasattr(fd.digest, "__wrapped__") else fd._digest(v)  # type: ignore[attr-defined]

    # If the original digest isn't wrapped, just reuse it directly
    # to represent "no change" semantics
    try:
        orig = fd.digest
    except Exception:  # pragma: no cover - defensive
        orig = None

    if orig is not None:
        monkeypatch.setattr(fd, "digest", orig, raising=True)

    cache.redigest()

    calls_after = set(cache.calls.list())
    values_after = set(cache.values.list())

    assert calls_after == calls_before
    assert values_after == values_before

    loaded = cache.load(key_before)
    assert loaded.arguments["a"] == [1, 2, (3, 4)]
    assert loaded.arguments["b"] == {"k": 10}
    assert loaded.result == ("x", {"y": 5})
