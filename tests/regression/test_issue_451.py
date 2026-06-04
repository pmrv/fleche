"""Regression test for issue #451: Cache.redigest() non-atomic save+evict.

``Cache.redigest()`` re-keys a call by saving it under its new lookup key and
then evicting the old key.  Previously this pair was not covered by any lock,
so a concurrent reader probing the affected keys could observe the call under
*both* keys (transient duplication) or — depending on ordering — under
*neither* (transient miss).

The fix holds the per-key locks for both the old and the new key across the
save+evict pair, so any concurrent ``load``/``contains``/``evict`` on either
key is serialized against the migration and never sees an intermediate state.
"""

import threading

import pytest

import fleche.digest as fd
from fleche.call import Call
from fleche.caches import Cache
from fleche.digest import Digest
from fleche.storage import CallMemory, ValueMemory


_NIBBLE_FLIP = {
    "0": "1", "1": "0", "2": "3", "3": "2", "4": "5", "5": "4", "6": "7",
    "7": "6", "8": "9", "9": "8", "a": "b", "b": "a", "c": "d", "d": "c",
    "e": "f", "f": "e",
}


def _calls_change_digest(orig_digest):
    """Patched digest that re-keys only Calls (values keep their digests).

    Digest tokens pass through unchanged so the value-storage keys stay stable;
    only a ``Call``'s own lookup digest changes, which is exactly what forces
    ``redigest()`` to re-key the entry.
    """

    def patched(value):
        if isinstance(value, Digest):
            return value
        if isinstance(value, Call):
            d = orig_digest(value)
            return Digest(d[:-1] + _NIBBLE_FLIP[d[-1]])
        return orig_digest(value)

    return patched


def test_redigest_save_evict_is_atomic(monkeypatch):
    """A concurrent reader never observes the call mid-migration.

    ``redigest()`` is paused (via a subclass that blocks inside ``evict``)
    while it holds the per-key locks for both the old and the new key.  A
    reader thread that probes those keys must block until the migration
    completes, and then sees the call under exactly one key — the new one.
    """
    reached_evict = threading.Event()
    release_evict = threading.Event()
    reader_done = threading.Event()

    class PausingCache(Cache):
        def evict(self, key):
            # redigest() calls this while holding both per-key locks; pause
            # here to open the save-then-evict window for the reader thread.
            reached_evict.set()
            assert release_evict.wait(timeout=5), "evict never released"
            return super().evict(key)

    c = PausingCache(ValueMemory({}), CallMemory({}))
    sample = Call(
        name="f",
        arguments={"x": 1},
        result=2,
        module=None,
        version=None,
        metadata={},
    )
    old_key = c.save(sample)

    # Flip the digest so redigest() re-keys the call under a new key.
    monkeypatch.setattr(fd, "digest", _calls_change_digest(fd.digest))
    new_key = sample.to_lookup_key()
    assert new_key != old_key

    snapshot: dict[str, bool] = {}

    def reader():
        # contains() acquires the old-key lock first; with the fix this blocks
        # until redigest() releases both locks.
        snapshot["old"] = c.contains(old_key)
        snapshot["new"] = c.contains(new_key)
        reader_done.set()

    redigest_thread = threading.Thread(target=c.redigest)
    redigest_thread.start()
    assert reached_evict.wait(timeout=5), "redigest never reached evict window"

    reader_thread = threading.Thread(target=reader)
    reader_thread.start()

    # The reader must not be able to observe the cache while redigest holds the
    # keys' locks.  If save+evict were not atomic it would complete here and
    # record a transient (True, True) duplication snapshot.
    assert not reader_done.wait(timeout=0.5), (
        "reader observed the cache mid-migration; save+evict is not atomic"
    )

    release_evict.set()
    redigest_thread.join(timeout=5)
    reader_thread.join(timeout=5)
    assert not redigest_thread.is_alive()
    assert reader_done.is_set()

    # After migration the call lives under the new key only.
    assert snapshot == {"old": False, "new": True}
    assert not c.contains(old_key)
    assert c.contains(new_key)
