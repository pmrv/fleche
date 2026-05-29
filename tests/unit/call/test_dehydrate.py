"""Tests for Call.stash, Call.digest, DigestedCall, and related methods."""
import pytest
from unittest.mock import MagicMock

from fleche.call import Call, DigestedCall, LazyCall
from fleche.caches import Cache
from fleche.digest import Digest, digest
from fleche.storage.base import SaveError
from fleche.storage.memory import ValueMemory, CallMemory


def _mem():
    return ValueMemory({})


def _cache(values=None):
    values = values or _mem()
    return Cache(values, CallMemory({}))


def _call(**kwargs):
    defaults = dict(name="f", arguments={"x": 1, "y": 2}, result=42)
    defaults.update(kwargs)
    return Call(**defaults)


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
    def test_fetch_returns_lazy_call(self):
        values = _mem()
        cache = _cache(values)
        call = _call()
        digested = call.stash(values)
        lazy = digested.fetch(cache)
        assert isinstance(lazy, LazyCall)

    def test_fetch_restores_arguments(self):
        values = _mem()
        cache = _cache(values)
        call = _call(arguments={"x": 10, "y": 20})
        digested = call.stash(values)
        restored = digested.fetch(cache).fetch()
        assert restored.arguments == {"x": 10, "y": 20}

    def test_fetch_restores_result(self):
        values = _mem()
        cache = _cache(values)
        call = _call(result=99)
        digested = call.stash(values)
        restored = digested.fetch(cache).fetch()
        assert restored.result == 99

    def test_fetch_preserves_metadata(self):
        values = _mem()
        cache = _cache(values)
        call = _call(metadata={"Runtime": {"elapsed": 2.5}})
        digested = call.stash(values)
        lazy = digested.fetch(cache)
        assert lazy.metadata == {"Runtime": {"elapsed": 2.5}}

    def test_fetch_roundtrip_lookup_key(self):
        values = _mem()
        cache = _cache(values)
        call = _call()
        lazy = call.stash(values).fetch(cache)
        assert lazy.to_lookup_key() == call.to_lookup_key()

    def test_fetch_none_result(self):
        """fetch handles DigestedCall with no result (result=None)."""
        dc = DigestedCall(name="f", arguments={})
        cache = _cache()
        lazy = dc.fetch(cache)
        assert isinstance(lazy, LazyCall)
        assert lazy._result is None
        # Accessing .result on a LazyCall with _result=None returns None
        # without consulting the value store.
        assert lazy.result is None


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
        values.save.side_effect = [result_digest, SaveError("cannot save")]
        call = _call(arguments={"x": 99})
        digested = call.stash(values)
        assert isinstance(digested.arguments["x"], Digest)

    def test_arg_save_non_save_error_propagates(self):
        values = MagicMock()
        result_digest = Digest("r" * 64)
        values.save.side_effect = [result_digest, RuntimeError("unexpected")]
        call = _call(arguments={"x": 99})
        with pytest.raises(RuntimeError, match="unexpected"):
            call.stash(values)

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


# ---------------------------------------------------------------------------
# DigestedCall.__digest__  —  cross-type digest equivalence
#
# DigestedCall.__digest__ ensures that digest(DigestedCall) == digest(Call) for
# semantically equivalent objects.  This invariant is load-bearing: it allows
# LazyCall.to_lookup_key() to delegate to DigestedCall without re-hashing raw
# values, and it means stored DigestedCall objects hash the same way as the
# original Call from which they were produced.
#
# The three-way equivalence that must hold:
#   digest(original_Call) == digest(DigestedCall) == digest(LazyCall)
# for objects representing the same function call.
# ---------------------------------------------------------------------------

class TestDigestedCallDigestEquivalence:
    """digest(DigestedCall) must equal digest(equivalent Call) and digest(equivalent LazyCall)."""

    def test_digested_call_digest_matches_original_call(self):
        """digest(dc) == digest(call) — Digest pass-through makes value vs pointer transparent."""
        call = _call(arguments={"x": 10, "y": 20}, result=99)
        dc = call.digest()
        assert digest(dc) == digest(call)

    def test_stash_digest_matches_original_call(self):
        """digest(stash) == digest(call) — stash stores values but same hash as original."""
        values = _mem()
        call = _call(arguments={"x": 10, "y": 20}, result=99)
        stashed = call.stash(values)
        assert digest(stashed) == digest(call)

    def test_digested_call_digest_matches_lazy_call(self):
        """digest(DigestedCall) == digest(LazyCall) — three-way equivalence."""
        values = _mem()
        cache = _cache(values)
        call = _call(arguments={"x": 10, "y": 20}, result=99)
        stashed = call.stash(values)
        lazy = stashed.fetch(cache)
        assert digest(stashed) == digest(lazy)
        assert digest(lazy) == digest(call)

    def test_digested_call_digest_stable_across_stash_fetch(self):
        """digest is stable after a full stash → fetch → fetch round-trip."""
        values = _mem()
        cache = _cache(values)
        call = _call(arguments={"x": 42}, result="hello")
        stashed = call.stash(values)
        restored = stashed.fetch(cache).fetch()
        assert digest(stashed) == digest(restored)

    def test_digested_call_digest_varies_with_arguments(self):
        """Different arguments produce different digests."""
        call_a = _call(arguments={"x": 1})
        call_b = _call(arguments={"x": 2})
        assert digest(call_a.digest()) != digest(call_b.digest())

    def test_digested_call_digest_varies_with_metadata(self):
        """Different metadata produces different full digests (metadata is NOT excluded from digest)."""
        call_a = _call(metadata={"Runtime": {"elapsed": 1.0}})
        call_b = _call(metadata={"Runtime": {"elapsed": 9.9}})
        assert digest(call_a.digest()) != digest(call_b.digest())


# ---------------------------------------------------------------------------
# LazyCall.detach  —  round-trip with DigestedCall.fetch
#
# Asserts field equality so any future LazyCall representation change that
# breaks the coupling between call.py and remote.py fails loudly here.
# ---------------------------------------------------------------------------

class TestLazyCallDetach:
    """LazyCall.detach() is the inverse of DigestedCall.fetch()."""

    def _lazy(self, **kwargs):
        values = _mem()
        cache = _cache(values)
        call = _call(**kwargs)
        stashed = call.stash(values)
        return stashed.fetch(cache)

    def test_returns_digested_call(self):
        lc = self._lazy()
        assert isinstance(lc.detach(), DigestedCall)

    def test_field_equality_with_originating_digested_call(self):
        """detach() reproduces every field of the DigestedCall it came from."""
        values = _mem()
        cache = _cache(values)
        call = _call(arguments={"x": 10, "y": 20}, result=42,
                     metadata={"Runtime": {"elapsed": 1.5}},
                     module="mymod", version=3, code_digest="abc")
        dc = call.stash(values)
        lc = dc.fetch(cache)
        dc2 = lc.detach()

        assert dc2.name == dc.name
        assert dc2.arguments == dc.arguments
        assert dc2.result == dc.result
        assert dc2.metadata == dc.metadata
        assert dc2.module == dc.module
        assert dc2.version == dc.version
        assert dc2.code_digest == dc.code_digest

    def test_round_trip_fetch_detach(self):
        """fetch(cache).detach() == original DigestedCall (field-wise)."""
        values = _mem()
        cache = _cache(values)
        call = _call()
        dc = call.stash(values)
        assert dc == dc.fetch(cache).detach()

    def test_detach_has_no_cache_reference(self):
        """The returned DigestedCall carries no _cache field."""
        lc = self._lazy()
        dc = lc.detach()
        assert not hasattr(dc, "_cache")

    def test_arguments_are_independent_copy(self):
        """Mutating the returned arguments dict does not affect the LazyCall."""
        lc = self._lazy()
        dc = lc.detach()
        dc.arguments["injected"] = Digest("a" * 64)
        assert "injected" not in lc._arguments

    def test_metadata_is_independent_copy(self):
        """Mutating the returned metadata dict does not affect the LazyCall."""
        lc = self._lazy(metadata={"Runtime": {"elapsed": 1.0}})
        dc = lc.detach()
        dc.metadata["injected"] = {}
        assert "injected" not in lc.metadata

    def test_lookup_key_preserved(self):
        """detach() preserves the lookup key."""
        values = _mem()
        cache = _cache(values)
        call = _call()
        lc = call.stash(values).fetch(cache)
        assert lc.detach().to_lookup_key() == call.to_lookup_key()
