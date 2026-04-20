"""Tests for Call.stash, Call.digest, DigestedCall, and related methods."""
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
# DigestedCall.from_call
# ---------------------------------------------------------------------------

class TestDigestedCallFromCall:
    def test_wraps_stored_call(self):
        call = _call(module="m", version=2, code_digest="abc")
        dc = DigestedCall.from_call(call)
        assert isinstance(dc, DigestedCall)
        assert dc.name == call.name
        assert dc.arguments is call.arguments
        assert dc.result is call.result
        assert dc.metadata is call.metadata
        assert dc.module == call.module
        assert dc.version == call.version
        assert dc.code_digest == call.code_digest

    def test_lookup_key_matches(self):
        call = _call()
        dc = DigestedCall.from_call(call)
        assert dc.to_lookup_key() == call.to_lookup_key()


# ---------------------------------------------------------------------------
# DigestedCall.to_lookup_key
# ---------------------------------------------------------------------------

class TestDigestedCallLookupKey:
    def test_matches_original_call(self):
        values = _mem()
        call = _call()
        digested = call.stash(values)
        assert digested.to_lookup_key() == call.to_lookup_key()

    def test_stable_across_stashes(self):
        values = _mem()
        call = _call()
        d1 = call.stash(values)
        d2 = call.stash(values)
        assert d1.to_lookup_key() == d2.to_lookup_key()

    def test_matches_digest(self):
        call = _call()
        assert call.digest().to_lookup_key() == call.to_lookup_key()

    def test_metadata_not_in_key(self):
        values = _mem()
        call_a = _call(metadata={"Runtime": {"elapsed": 1.0}})
        call_b = _call(metadata={"Runtime": {"elapsed": 9.9}})
        assert call_a.stash(values).to_lookup_key() == call_b.stash(values).to_lookup_key()

    def test_metadata_preserved(self):
        values = _mem()
        call = _call(metadata={"Runtime": {"elapsed": 1.5}})
        digested = call.stash(values)
        assert digested.metadata == {"Runtime": {"elapsed": 1.5}}

    def test_module_version_code_digest_preserved(self):
        values = _mem()
        call = _call(module="mymod", version=3, code_digest="abc123")
        digested = call.stash(values)
        assert digested.module == "mymod"
        assert digested.version == 3
        assert digested.code_digest == "abc123"


# ---------------------------------------------------------------------------
# DigestedCall.fetch
# ---------------------------------------------------------------------------

class TestDigestedCallFetch:
    def test_fetch_returns_call(self):
        values = _mem()
        call = _call()
        digested = call.stash(values)
        restored = digested.fetch(values)
        assert isinstance(restored, Call)

    def test_fetch_restores_arguments(self):
        values = _mem()
        call = _call(arguments={"x": 10, "y": 20})
        digested = call.stash(values)
        restored = digested.fetch(values)
        assert restored.arguments == {"x": 10, "y": 20}

    def test_fetch_restores_result(self):
        values = _mem()
        call = _call(result=99)
        digested = call.stash(values)
        restored = digested.fetch(values)
        assert restored.result == 99

    def test_fetch_preserves_metadata(self):
        values = _mem()
        call = _call(metadata={"Runtime": {"elapsed": 2.5}})
        digested = call.stash(values)
        restored = digested.fetch(values)
        assert restored.metadata == {"Runtime": {"elapsed": 2.5}}

    def test_fetch_roundtrip_lookup_key(self):
        values = _mem()
        call = _call()
        restored = call.stash(values).fetch(values)
        assert restored.to_lookup_key() == call.to_lookup_key()

    def test_fetch_none_result(self):
        """fetch handles DigestedCall with no result (result=None)."""
        dc = DigestedCall(name="f", arguments={})
        values = _mem()
        restored = dc.fetch(values)
        assert restored.result is None


# ---------------------------------------------------------------------------
# Call.stash
# ---------------------------------------------------------------------------

class TestCallStash:
    def test_returns_digested_call(self):
        values = _mem()
        call = _call()
        result = call.stash(values)
        assert isinstance(result, DigestedCall)

    def test_arguments_are_digests(self):
        values = _mem()
        call = _call()
        digested = call.stash(values)
        for v in digested.arguments.values():
            assert isinstance(v, Digest)

    def test_result_is_digest(self):
        values = _mem()
        call = _call()
        digested = call.stash(values)
        assert isinstance(digested.result, Digest)

    def test_already_digest_argument_preserved(self):
        values = _mem()
        existing_digest = Digest("a" * 64)
        call = _call(arguments={"x": existing_digest})
        digested = call.stash(values)
        assert digested.arguments["x"] == existing_digest

    def test_already_digest_argument_not_saved(self):
        values = MagicMock()
        values.save.return_value = Digest("b" * 64)
        existing_digest = Digest("a" * 64)
        call = _call(arguments={"x": existing_digest})
        call.stash(values)
        # values.save should only be called for the result, not for the Digest arg
        assert values.save.call_count == 1

    def test_arg_save_failure_falls_back_to_digest(self):
        values = MagicMock()
        result_digest = Digest("r" * 64)
        values.save.side_effect = [result_digest, Exception("cannot save")]
        call = _call(arguments={"x": 99})
        digested = call.stash(values)
        assert isinstance(digested.arguments["x"], Digest)

    def test_result_save_failure_propagates(self):
        values = MagicMock()
        values.save.side_effect = RuntimeError("storage full")
        call = _call()
        with pytest.raises(RuntimeError, match="storage full"):
            call.stash(values)


# ---------------------------------------------------------------------------
# Call.digest
# ---------------------------------------------------------------------------

class TestCallDigest:
    def test_returns_digested_call(self):
        assert isinstance(_call().digest(), DigestedCall)

    def test_arguments_are_digests(self):
        for v in _call().digest().arguments.values():
            assert isinstance(v, Digest)

    def test_result_is_digest(self):
        assert isinstance(_call().digest().result, Digest)

    def test_same_lookup_key_as_stash(self):
        values = _mem()
        call = _call()
        assert call.digest().to_lookup_key() == call.stash(values).to_lookup_key()

    def test_already_digest_argument_preserved(self):
        existing = Digest("a" * 64)
        digested = _call(arguments={"x": existing}).digest()
        assert digested.arguments["x"] == existing

    def test_metadata_preserved(self):
        call = _call(metadata={"Tags": {"env": "prod"}})
        assert call.digest().metadata == {"Tags": {"env": "prod"}}
