"""Regression reproducer: wrap_executor payload carries an unpicklable lock.

``wrap_executor``'s patched ``submit`` hands the underlying executor
``func.fleche.bind(*args)`` — a :class:`~fleche.BoundWrapper` wrapping
``functools.partial(wrapper, *args)``, where ``wrapper`` is the closure built
by :func:`fleche.wrapper.make_wrapper`.  That closure closes over

    _in_flight_lock = threading.Lock()   # a raw _thread.lock

(see ``src/fleche/wrapper.py``).  A raw lock is unpicklable.

Why this matters: a cloudpickling **cluster backend** (executorlib, dask, ...)
ships user code *by value* so worker nodes need not import it — commonly via
``cloudpickle.register_pickle_by_value(module)``, and always for functions
defined in ``__main__`` or a notebook.  Serialising ``wrapper`` by value walks
its closure cells and hits the lock:

    TypeError: cannot pickle '_thread.lock' object

So ``wrap_executor`` + a cloudpickling cluster backend fundamentally cannot
ship the wrapper.  The "just drop it into ``wrap_executor``" prose in
``docs/parallel_execution.rst`` (the ``ProcessPoolExecutor`` / executorlib
examples) was never actually exercised on this path — in an ordinary
importable module cloudpickle serialises ``wrapper`` *by reference*, so the
closure cells (and the lock) are never touched.

This test pins the *root cause* directly and deterministically: the wrapper
closure that ends up inside the ``wrap_executor`` payload must not carry a
raw, unpicklable lock.  It deliberately does **not** call ``cloudpickle`` —
the exact by-value failure varies by cloudpickle/Python version (older
cloudpickle raises ``IndexError`` from its bytecode walk before it ever
reaches the lock), which would make an end-to-end pickle assertion a flaky,
version-dependent sentinel.  Inspecting the closure is exact and stable.

Marked ``xfail(strict=True)`` so it flips to a hard failure the moment the
wrapper stops closing over an unpicklable lock (e.g. the lock is
reconstructed lazily, or given ``__reduce__`` support) — i.e. when the payload
becomes shippable to a cloudpickling backend.
"""

import functools
import pickle
import threading

import pytest

import fleche

_LOCK_TYPE = type(threading.Lock())


@fleche.fleche
def _sample_iso(i):
    return i * i


def _unwrap_payload_callable(bound):
    """Return the ``make_wrapper`` closure buried inside a bind() payload.

    ``func.fleche.bind(*args)`` yields a ``BoundWrapper`` whose ``func`` is
    ``functools.partial(wrapper, *args)`` (or ``wrapper`` itself when no args
    are bound).  A cluster backend must serialise exactly this object.
    """
    func = bound.func
    if isinstance(func, functools.partial):
        func = func.func
    return func


@pytest.mark.xfail(
    strict=True,
    reason="make_wrapper's closure closes over a raw threading.Lock, so the "
    "wrap_executor payload cannot be cloudpickled by value (cluster backends)",
    raises=AssertionError,
)
def test_wrap_executor_payload_has_no_unpicklable_lock():
    """The wrap_executor payload must not carry an unpicklable object by value.

    This is exactly what a cloudpickling cluster backend has to ship, and the
    raw ``threading.Lock`` in the wrapper closure is what makes it fail.
    """
    wrapper = _unwrap_payload_callable(_sample_iso.fleche.bind(3))

    lock_cells = [
        cell.cell_contents
        for cell in (wrapper.__closure__ or ())
        if isinstance(cell.cell_contents, _LOCK_TYPE)
    ]

    # Sanity: if the wrapper ever stops carrying a lock at all, this test has
    # become stale rather than passing for the right reason — surface that.
    if lock_cells:
        with pytest.raises(TypeError, match="cannot pickle"):
            pickle.dumps(lock_cells[0])

    assert not lock_cells, (
        "make_wrapper's wrapper closure carries a raw, unpicklable lock "
        f"({lock_cells!r}); a cloudpickling cluster backend that ships the "
        "wrap_executor payload by value fails with "
        "\"cannot pickle '_thread.lock' object\"."
    )
