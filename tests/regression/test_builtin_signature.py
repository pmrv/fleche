"""Wrapping a C builtin (e.g. ``time.sleep``) used to crash with
``ValueError: no signature found for builtin`` because ``inspect.signature``
cannot introspect builtins lacking ``__text_signature__``.  The wrapper now
falls back to a permissive ``(*args, **kwargs)`` signature so decoration and
invocation both succeed.
"""
import time

from fleche import fleche
from fleche.caches import Cache
from fleche.storage import memory
import fleche.state as state


def test_wrapping_builtin_sleep_does_not_crash():
    cache = Cache(values=memory.ValueMemory(storage={}), calls=memory.CallMemory(storage={}))
    token = state._CACHE.set(cache)
    try:
        cached_sleep = fleche()(time.sleep)
        # Decoration and call both succeed despite sleep lacking a signature.
        assert cached_sleep(0) is None
    finally:
        state._CACHE.reset(token)


def test_wrapping_builtin_with_return_value_caches():
    """A builtin that returns a non-None result should still cache via the permissive signature."""
    calls_storage = memory.CallMemory(storage={})
    cache = Cache(values=memory.ValueMemory(storage={}), calls=calls_storage)
    token = state._CACHE.set(cache)
    try:
        # int() is a builtin that lacks an inspect-friendly signature in some versions
        cached_abs = fleche()(abs)
        assert cached_abs(-3) == 3
        assert cached_abs(-3) == 3  # cache hit
        assert len(calls_storage.storage) == 1
    finally:
        state._CACHE.reset(token)
