"""Tests for ``Digest.expand`` and ``Digest.shrink`` instance helpers.

These methods are thin convenience wrappers that delegate to the active (or
explicitly supplied) cache.  They are part of the public ``Digest`` API and
are documented as such, but were not directly exercised by any test.

Coverage targets ``digest.py`` lines 35-38 (``Digest.expand``) and 49-52
(``Digest.shrink``), including both branches of the ``if cache is None``
gate in each method.
"""

import pytest

from fleche import cache as active_cache
from fleche.call import Call
from fleche.caches import Cache
from fleche.digest import Digest
from fleche.storage import ValueMemory, CallMemory


def _populated_cache() -> tuple[Cache, Digest]:
    cache = Cache(ValueMemory({}), CallMemory({}))
    call = Call(
        name="f", arguments={"a": 1}, result="r",
        module="m", version="1.0", metadata={},
    )
    return cache, cache.save(call)


def test_digest_expand_with_explicit_cache_forwards_to_cache():
    cache, full = _populated_cache()
    short = Digest(full[:6])

    assert short.expand(cache=cache) == full


def test_digest_expand_without_cache_uses_active_cache():
    cache, full = _populated_cache()
    short = Digest(full[:6])

    with active_cache(cache):
        assert short.expand() == full


def test_digest_shrink_with_explicit_cache_forwards_to_cache():
    cache, full = _populated_cache()

    shortened = full.shrink(cache=cache)

    assert isinstance(shortened, Digest)
    assert cache.expand(shortened) == full


def test_digest_shrink_without_cache_uses_active_cache():
    cache, full = _populated_cache()

    with active_cache(cache):
        shortened = full.shrink()

    assert isinstance(shortened, Digest)
    assert cache.expand(shortened) == full


def test_digest_expand_unknown_key_propagates_keyerror():
    cache = Cache(ValueMemory({}), CallMemory({}))

    with pytest.raises(KeyError):
        Digest("deadbeef").expand(cache=cache)
