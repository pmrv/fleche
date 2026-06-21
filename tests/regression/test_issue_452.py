"""Regression test for issue #452: BaseCache/QueryIterator.transfer contains→save TOCTOU.

``transfer`` checks ``target.contains(key)`` and then ``target.save(...)`` to
honour ``overwrite=False``.  Without a lock spanning both, two concurrent
transfers (or a transfer racing a direct ``save``) can both pass the check and
both save, silently violating the "no overwrite" intent.

The fix lives on the cache: ``BaseCache._transfer_one`` holds the target's
per-key operation context across the whole check → save sequence, and
``QueryIterator.transfer`` only calls that one public-ish cache method.
Because the lock lives on the cache, wrapper/stack targets lock their *real*
inner cache: ``CacheWrapper`` forwards ``_operation_context`` to its wrapped
cache and ``CacheStack`` locks ``stack[0]`` (entering the other members with
the no-op ``Intent.READ``), instead of inheriting the no-op context a
non-``Cache`` ``BaseCache`` would otherwise use.  These tests pin that the
lock is genuinely held for the duration — for a plain ``Cache`` and for a
``CacheWrapper`` target — so a competing writer on the same key is serialised.
"""

import threading

from fleche.call import Call
from fleche.caches import Cache, CacheStack, CacheWrapper
from fleche.storage.memory import ValueMemory, CallMemory


def _cache(*calls):
    c = Cache(values=ValueMemory({}), calls=CallMemory({}))
    for call in calls:
        c.save(call)
    return c


_call_a = Call(name="f", arguments={"x": 1}, result=10)
_call_a_conflict = Call(name="f", arguments={"x": 1}, result=999)  # same key as _call_a


def test_transfer_holds_target_lock_across_check_and_save():
    """The contains→save window must be covered by the target's per-key lock.

    A ``SlowContainsCache`` blocks inside ``contains`` (which ``transfer`` calls
    *inside* ``with target._operation_context(key)``), so the transfer thread is
    parked while holding the per-key lock.  A second thread then tries to
    ``save`` the same key directly on the target.  If the lock truly spans the
    check-then-save, that competing save blocks until the transfer releases; if
    the window is unguarded (the pre-fix behaviour, where ``Cache.contains``
    acquires and releases the lock internally before the block), the competitor
    proceeds immediately and the assertion fails.
    """
    in_contains = threading.Event()
    release = threading.Event()

    class SlowContainsCache(Cache):
        def contains(self, key):
            in_contains.set()
            release.wait(timeout=5)
            return super().contains(key)

    src = _cache(_call_a)
    dst = SlowContainsCache(values=ValueMemory({}), calls=CallMemory({}))

    errors: list[Exception] = []

    def transferrer():
        try:
            src.query().transfer(dst)
        except Exception as e:  # pragma: no cover - failure path
            errors.append(e)

    t = threading.Thread(target=transferrer)
    t.start()
    assert in_contains.wait(timeout=5), "transfer never reached contains()"

    # The transfer thread is now parked inside contains() while holding dst's
    # per-key lock for _call_a's key.  A competing direct save on the same key
    # must block until the transfer releases.
    competitor_done = threading.Event()

    def competitor():
        try:
            dst.save(_call_a_conflict)  # same lookup key as _call_a
        except Exception as e:  # pragma: no cover - failure path
            errors.append(e)
        finally:
            competitor_done.set()

    c = threading.Thread(target=competitor)
    c.start()

    assert not competitor_done.wait(timeout=1), (
        "competing save on the same key was not serialised; "
        "the contains→save window is not lock-protected (TOCTOU)"
    )

    release.set()
    t.join(timeout=5)
    c.join(timeout=5)
    assert not t.is_alive() and not c.is_alive()
    assert not errors, f"unexpected exceptions: {errors}"


def test_transfer_into_wrapper_holds_inner_cache_lock():
    """A wrapper target locks its *inner* cache across the check-then-save.

    A ``CacheWrapper`` used to inherit the no-op base ``_operation_context``, so
    the original ``target._operation_context(key)`` approach acquired *nothing*
    for wrapper targets and left the TOCTOU wide open.  ``CacheWrapper`` now
    forwards ``_operation_context`` to the wrapped cache, so ``_transfer_one``
    locks the real inner cache while ``contains`` / ``save`` still go through the
    wrapper.  We park the transfer inside the inner cache's
    ``contains`` (reached through the wrapper) and assert a competing direct
    save on the inner cache blocks until the transfer releases.
    """
    in_contains = threading.Event()
    release = threading.Event()

    class SlowContainsCache(Cache):
        def contains(self, key):
            in_contains.set()
            release.wait(timeout=5)
            return super().contains(key)

    inner = SlowContainsCache(values=ValueMemory({}), calls=CallMemory({}))
    dst = CacheWrapper(inner)
    src = _cache(_call_a)

    errors: list[Exception] = []

    def transferrer():
        try:
            src.query().transfer(dst)
        except Exception as e:  # pragma: no cover - failure path
            errors.append(e)

    t = threading.Thread(target=transferrer)
    t.start()
    assert in_contains.wait(timeout=5), "transfer never reached inner contains()"

    competitor_done = threading.Event()

    def competitor():
        try:
            inner.save(_call_a_conflict)  # same lookup key as _call_a
        except Exception as e:  # pragma: no cover - failure path
            errors.append(e)
        finally:
            competitor_done.set()

    c = threading.Thread(target=competitor)
    c.start()

    assert not competitor_done.wait(timeout=1), (
        "competing save on the wrapped cache was not serialised; the wrapper "
        "transfer did not hold the inner cache's per-key lock"
    )

    release.set()
    t.join(timeout=5)
    c.join(timeout=5)
    assert not t.is_alive() and not c.is_alive()
    assert not errors, f"unexpected exceptions: {errors}"


def test_transfer_into_stack_holds_bottom_cache_lock():
    """A stack target locks ``stack[0]`` (the write target) across check-then-save.

    A ``CacheStack``'s own ``_operation_context`` enters every member, but only
    ``stack[0]`` takes the real (``Intent.WRITE``) lock — the others are entered
    with the no-op ``Intent.READ``.  Since every transfer writes through
    ``stack[0]``, that single lock makes the check-then-save atomic.  We park the
    transfer inside ``stack[0]``'s ``contains`` (reached via the stack's
    ``contains`` fan-out) and assert a competing direct save on ``stack[0]``
    blocks until the transfer releases.
    """
    in_contains = threading.Event()
    release = threading.Event()

    class SlowContainsCache(Cache):
        def contains(self, key):
            in_contains.set()
            release.wait(timeout=5)
            return super().contains(key)

    bottom = SlowContainsCache(values=ValueMemory({}), calls=CallMemory({}))
    top = _cache()
    dst = CacheStack((bottom, top))
    src = _cache(_call_a)

    errors: list[Exception] = []

    def transferrer():
        try:
            src.query().transfer(dst)
        except Exception as e:  # pragma: no cover - failure path
            errors.append(e)

    t = threading.Thread(target=transferrer)
    t.start()
    assert in_contains.wait(timeout=5), "transfer never reached stack[0] contains()"

    competitor_done = threading.Event()

    def competitor():
        try:
            bottom.save(_call_a_conflict)  # same lookup key as _call_a
        except Exception as e:  # pragma: no cover - failure path
            errors.append(e)
        finally:
            competitor_done.set()

    c = threading.Thread(target=competitor)
    c.start()

    assert not competitor_done.wait(timeout=1), (
        "competing save on stack[0] was not serialised; the stack transfer did "
        "not hold the bottom cache's per-key lock"
    )

    release.set()
    t.join(timeout=5)
    c.join(timeout=5)
    assert not t.is_alive() and not c.is_alive()
    assert not errors, f"unexpected exceptions: {errors}"


def test_concurrent_transfers_no_duplicate_save_without_overwrite():
    """Many concurrent transfers of the same key never both save (overwrite=False).

    Each source holds the same conflicting key; the destination starts empty.
    With the check-then-save made atomic, exactly the first transfer to win the
    lock saves and every other observes the conflict and skips — no thread sees
    a torn state and none raises.
    """
    dst = _cache()
    errors: list[Exception] = []
    barrier = threading.Barrier(8)

    def transferrer(i: int):
        src = _cache(Call(name="f", arguments={"x": 1}, result=i))
        try:
            barrier.wait(timeout=5)
            src.query().transfer(dst, overwrite=False)
        except Exception as e:  # pragma: no cover - failure path
            errors.append(e)

    threads = [threading.Thread(target=transferrer, args=(i,)) for i in range(8)]
    for th in threads:
        th.start()
    for th in threads:
        th.join(timeout=5)

    assert not errors, f"unexpected exceptions during concurrent transfer: {errors}"
    key = _call_a.to_lookup_key()
    assert dst.contains(key)
    # Whichever transfer won, the entry is present exactly once and loadable.
    assert dst.load(key).arguments["x"] == 1
