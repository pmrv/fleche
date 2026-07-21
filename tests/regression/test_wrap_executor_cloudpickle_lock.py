"""Regression: the wrap_executor payload is cloudpicklable by value.

``wrap_executor``'s patched ``submit`` hands the underlying executor
``func.fleche.bind(*args)`` — a :class:`~fleche.BoundWrapper` wrapping
``functools.partial(wrapper, *args)``, where ``wrapper`` is the closure built
by :func:`fleche.wrapper.make_wrapper`.  That closure used to close over a raw
``threading.Lock`` (``_in_flight_lock``), which is unpicklable.

A cloudpickling cluster backend (executorlib, dask, ...) ships user code *by
value* whenever it cannot assume the worker can import it.  That happens far
more easily than by ``__main__`` / notebooks or an explicit
``register_pickle_by_value``: simply **rebinding** a decorated function to a
name other than its own — ``func = fleche.fleche(some_other)`` — is enough.
The wrapper carries ``@wraps(some_other)``, so its ``__qualname__`` is
``some_other``; cloudpickle's by-reference lookup finds the *plain* function
(or nothing) under that name, not the wrapper, and falls back to by value —
walking the closure cells and, formerly, hitting the lock:

    TypeError: cannot pickle '_thread.lock' object

(The ordinary ``@fleche.fleche`` decorator form dodges this, because the
decorated name shadows the original and by-reference lookup resolves back to
the wrapper — which is why the happy-path docs examples never exercised it.)

The fix bundles the in-flight map and its lock into a small picklable helper
(:class:`fleche.wrapper._InFlight`) that reconstructs fresh on unpickle, so the
wrapper serialises by value.  These tests guard that.
"""

import functools
import threading

import pytest

import fleche
from fleche.caches import Cache
from fleche.storage.memory import ValueMemory, CallMemory

_LOCK_TYPE = type(threading.Lock())


def _plain_iso(i):
    return i * i


# Rebind the decorated wrapper to a name other than its __qualname__
# ('_plain_iso').  In an ordinary importable module this alone forces
# cloudpickle onto its by-value path — exactly where the wrapper closure (and
# formerly its lock) must be serialised.
_rebound_iso = fleche.fleche(_plain_iso)


def _wrapper_closure(bound):
    """Return the make_wrapper closure buried in a ``bind()`` payload."""
    func = bound.func
    if isinstance(func, functools.partial):
        func = func.func
    return func


def test_wrap_executor_payload_has_no_raw_lock_in_closure():
    """The wrapper closure must not carry a raw, unpicklable lock.

    Deterministic and version-independent — it never invokes cloudpickle, so
    it holds even on environments whose cloudpickle cannot serialise the
    wrapper's bytecode by value for unrelated reasons.
    """
    wrapper = _wrapper_closure(_rebound_iso.fleche.bind(3))

    raw_locks = [
        cell.cell_contents
        for cell in (wrapper.__closure__ or ())
        if isinstance(cell.cell_contents, _LOCK_TYPE)
    ]

    assert not raw_locks, (
        "make_wrapper's wrapper closure carries a raw threading.Lock "
        f"({raw_locks!r}); this makes the wrap_executor payload unpicklable by "
        "value, so a cloudpickling cluster backend cannot ship it."
    )


def test_wrap_executor_payload_cloudpickles_by_value():
    """End-to-end: the by-value payload survives a cloudpickle round-trip.

    Skipped only when the environment's cloudpickle cannot serialise the
    wrapper by value for a reason unrelated to the lock (older cloudpickle
    releases raise ``IndexError`` from their bytecode walk on newer Python);
    a re-emergence of the lock ``TypeError`` still fails loudly.
    """
    cloudpickle = pytest.importorskip("cloudpickle")

    with fleche.cache(Cache(ValueMemory({}), CallMemory({}))):
        payload = _rebound_iso.fleche.bind(3)

    try:
        data = cloudpickle.dumps(payload)
    except TypeError as exc:
        if "_thread.lock" in str(exc):
            raise  # the regression these tests guard against
        pytest.skip(f"cloudpickle cannot serialise the wrapper here: {exc}")
    except Exception as exc:  # e.g. old cloudpickle's bytecode-walk IndexError
        pytest.skip(f"cloudpickle by-value unsupported in this env: {exc!r}")

    assert cloudpickle.loads(data)() == 9
