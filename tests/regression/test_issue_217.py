"""Regression test for issue #217.

``CacheStack.load()`` back-fills a hit from a higher cache into the base
cache.  Before the fix this transfer was unprotected: multiple threads loading
the same key would all miss the base, all hit the higher cache, and all call
``self.save(...)`` on the base concurrently — running the base's non-atomic
check-evict-save many times over.

The fix serializes the back-fill per key and double-checks ``contains`` under
the lock, so the transfer happens exactly once no matter how many threads race.
"""

import threading
import time
from dataclasses import dataclass

from fleche.caches import Cache, CacheStack
from fleche.call import Call
from fleche.storage import ValueMemory, CallMemory


def test_concurrent_backfill_transfers_once():
    save_calls: list[int] = []
    barrier = threading.Barrier(8)

    @dataclass(frozen=True)
    class CountingCache(Cache):
        """Base cache that records every save and widens the race window."""

        def save(self, call: Call) -> str:
            save_calls.append(1)
            # Sleep while holding the per-key back-fill lock so that, without
            # serialization, all eight threads would pile into save() at once.
            time.sleep(0.05)
            return super().save(call)

    base = CountingCache(ValueMemory({}), CallMemory({}))
    top = Cache(ValueMemory({}), CallMemory({}))

    call = Call(name="compute", arguments={"x": 42}, result=84)
    key = top.save(call)

    stack = CacheStack((base, top))

    results: list[object] = []
    results_lock = threading.Lock()

    def worker():
        barrier.wait()
        lc = stack.load(key)
        with results_lock:
            results.append(lc.result)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # Every thread observed the correct result ...
    assert results == [84] * 8
    # ... but the back-fill ran exactly once despite the concurrent race.
    assert len(save_calls) == 1
    # ... and the key is now present in the base cache.
    assert base.contains(key)
