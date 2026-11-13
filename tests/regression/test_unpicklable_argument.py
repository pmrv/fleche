"""An argument the value store cannot serialise must not take the call out of the cache.

``Call._to_digested`` already degrades an unsaveable argument to a digest-only reference --
the value is hashed into the key but not stored -- and that branch keys on ``SaveError``.
The pickle-family backends used to let the serializer's own ``TypeError`` escape instead, so
``cache.prepare`` raised, ``wrapper._run_and_cache`` logged "Cache failed to prepare call"
and ran the body uncached. Every call taking such an argument then recomputed, forever,
behind a warning.

Found against a real workload: an ASE property-test suite passing a ``PyACECalculator`` (which
holds a ``pyace.evaluator.ACEBEvaluator``, a C++ object) to every cached function. The suite
digested the calculator fine through a registered digest hook -- the keys were correct -- and
still cached nothing at all: 248 refusals in one run, and a second pass over the same cache
that was no faster than the first.
"""
import pytest

from fleche import fleche
from fleche.caches import Cache
from fleche.storage.pickle_file import ValuePickleFile, CallPickleFile
import fleche.state as state


class Opaque:
    """Digestible by identity, unserialisable by pickle -- like a wrapped C++ handle."""

    def __init__(self, tag):
        self.tag = tag

    def __digest__(self):
        from fleche.digest import digest
        return digest(("Opaque", self.tag))

    def __reduce__(self):
        raise TypeError("cannot pickle 'Opaque' object")


@pytest.fixture
def file_cache(tmp_path):
    cache = Cache(values=ValuePickleFile(root=tmp_path / "values"),
                  calls=CallPickleFile(root=tmp_path / "calls"))
    token = state._CACHE.set(cache)
    try:
        yield cache
    finally:
        state._CACHE.reset(token)


def test_unpicklable_argument_is_still_cached(file_cache):
    calls = []

    @fleche()
    def work(handle, n):
        calls.append((handle.tag, n))
        return n * 2

    assert work(Opaque("ace"), 3) == 6
    assert work(Opaque("ace"), 3) == 6
    assert calls == [("ace", 3)], "the second call must have come from the cache"


def test_the_unpicklable_argument_is_still_part_of_the_key(file_cache):
    """Degrading to a digest-only reference must not collapse distinct arguments together."""
    calls = []

    @fleche()
    def work(handle):
        calls.append(handle.tag)
        return handle.tag.upper()

    assert work(Opaque("a")) == "A"
    assert work(Opaque("b")) == "B"
    assert work(Opaque("a")) == "A"
    assert work(Opaque("b")) == "B"
    assert calls == ["a", "b"], "two entries, one per handle, and both hit on the repeat"
