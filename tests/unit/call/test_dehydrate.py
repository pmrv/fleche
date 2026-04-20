"""Tests for Call.dehydrate and DigestedCall."""
import pytest
from unittest.mock import MagicMock

from fleche.call import Call, DigestedCall
from fleche.digest import Digest
from fleche.storage.memory import ValueMemory


def _mem():
    return ValueMemory({})


def _call(**kwargs):
    defaults = dict(name="f", arguments={"x": 1, "y": 2}, result=42)
    defaults.update(kwargs)
    return Call(**defaults)


# ---------------------------------------------------------------------------
# DigestedCall
# ---------------------------------------------------------------------------

class TestDigestedCall:
    def test_to_lookup_key_matches_original_call(self):
        values = _mem()
        call = _call()
        digested = call.dehydrate(values)
        assert digested.to_lookup_key() == call.to_lookup_key()

    def test_to_lookup_key_stable_across_dehydrations(self):
        values = _mem()
        call = _call()
        d1 = call.dehydrate(values)
        d2 = call.dehydrate(values)
        assert d1.to_lookup_key() == d2.to_lookup_key()

    def test_metadata_preserved(self):
        values = _mem()
        call = _call(metadata={"Runtime": {"elapsed": 1.5}})
        digested = call.dehydrate(values)
        assert digested.metadata == {"Runtime": {"elapsed": 1.5}}

    def test_module_version_code_digest_preserved(self):
        values = _mem()
        call = _call(module="mymod", version=3, code_digest="abc123")
        digested = call.dehydrate(values)
        assert digested.module == "mymod"
        assert digested.version == 3
        assert digested.code_digest == "abc123"


# ---------------------------------------------------------------------------
# Call.dehydrate
# ---------------------------------------------------------------------------

class TestCallDehydrate:
    def test_returns_digested_call(self):
        values = _mem()
        call = _call()
        result = call.dehydrate(values)
        assert isinstance(result, DigestedCall)

    def test_arguments_are_digests(self):
        values = _mem()
        call = _call()
        digested = call.dehydrate(values)
        for v in digested.arguments.values():
            assert isinstance(v, Digest)

    def test_result_is_digest(self):
        values = _mem()
        call = _call()
        digested = call.dehydrate(values)
        assert isinstance(digested.result, Digest)

    def test_already_digest_argument_preserved(self):
        values = _mem()
        existing_digest = Digest("a" * 64)
        call = _call(arguments={"x": existing_digest})
        digested = call.dehydrate(values)
        assert digested.arguments["x"] == existing_digest

    def test_already_digest_argument_not_saved(self):
        values = MagicMock()
        values.save.return_value = Digest("b" * 64)
        existing_digest = Digest("a" * 64)
        call = _call(arguments={"x": existing_digest})
        call.dehydrate(values)
        # values.save should only be called for the result, not for the Digest arg
        assert values.save.call_count == 1

    def test_arg_save_failure_falls_back_to_digest(self):
        values = MagicMock()
        result_digest = Digest("r" * 64)
        values.save.side_effect = [result_digest, Exception("cannot save")]
        call = _call(arguments={"x": 99})
        digested = call.dehydrate(values)
        # Should not raise; argument falls back to a Digest
        assert isinstance(digested.arguments["x"], Digest)

    def test_result_save_failure_propagates(self):
        values = MagicMock()
        values.save.side_effect = RuntimeError("storage full")
        call = _call()
        with pytest.raises(RuntimeError, match="storage full"):
            call.dehydrate(values)

    def test_roundtrip_lookup_key(self):
        """Saving and reloading via in-memory storage preserves the lookup key."""
        from fleche.storage.memory import CallMemory
        from fleche.caches import Cache

        values = _mem()
        calls = CallMemory({})
        cache = Cache(values, calls)

        call = Call(name="g", arguments={"a": [1, 2], "b": {"k": 10}}, result=("x", 5))
        key = cache.save(call)
        loaded = cache.load(key, lazy=False)
        assert loaded.to_lookup_key() == key
