"""Regression reproducer: wrap_executor payload can't be cloudpickled by value.

``wrap_executor``'s patched ``submit`` hands the underlying executor
``func.fleche.bind(*args)`` — a :class:`~fleche.BoundWrapper` wrapping
``functools.partial(wrapper, *args)``, where ``wrapper`` is the closure built
by :func:`fleche.wrapper.make_wrapper`.  That closure closes over

    _in_flight_lock = threading.Lock()   # a raw _thread.lock

(see ``src/fleche/wrapper.py``).  A raw lock is unpicklable.

Why the happy-path docs never caught this: when the decorated function lives
in an ordinary importable module, cloudpickle serialises ``wrapper`` *by
reference* — its ``@wraps``-copied ``__qualname__`` resolves back to the
decorated name — so the closure cells (and the lock) are never touched.

But a cloudpickling **cluster backend** (executorlib, dask, ...) ships user
code *by value* so worker nodes need not import it — commonly via
``cloudpickle.register_pickle_by_value(module)``, and always for functions
defined in ``__main__`` or a notebook.  By value, cloudpickle walks the
closure cells and hits the lock:

    TypeError: cannot pickle '_thread.lock' object

So ``wrap_executor`` + a cloudpickling cluster backend fundamentally cannot
ship the wrapper.  The "just drop it into ``wrap_executor``" prose in
``docs/parallel_execution.rst`` (the ``ProcessPoolExecutor`` / executorlib
examples) was never actually exercised on this path.

This test reproduces the failure without a real cluster by asking cloudpickle
to pickle the exact payload ``wrap_executor`` builds, under the by-value
regime a cluster backend imposes.  It is marked ``xfail(strict=True)`` so it
flips to a failure the moment the wrapper is made picklable (e.g. by giving
the lock ``__reduce__`` support, or reconstructing it lazily).
"""

import concurrent.futures
import sys

import pytest

import fleche
from fleche.caches import Cache
from fleche.storage.memory import ValueMemory, CallMemory

cloudpickle = pytest.importorskip("cloudpickle")


@fleche.fleche
def _sample_iso(i):
    return i * i


@pytest.mark.xfail(
    strict=True,
    reason="wrapper closes over a threading.Lock; cloudpickle-by-value "
    "(cluster backends) cannot serialise the wrap_executor payload",
    raises=TypeError,
)
def test_wrap_executor_payload_cloudpickles_by_value():
    """The payload wrap_executor submits must survive by-value cloudpickling.

    Registering this test's module for by-value pickling reproduces exactly
    what a cloudpickling cluster backend does when it can't assume the worker
    can import the user's code.
    """
    this_module = sys.modules[__name__]
    cloudpickle.register_pickle_by_value(this_module)
    try:
        cache = Cache(ValueMemory({}), CallMemory({}))
        with fleche.cache(cache):
            with concurrent.futures.ThreadPoolExecutor() as executor:
                fleche.wrap_executor(executor)
                # Exactly the payload wrap_executor.submit() builds before it
                # calls the underlying (cluster) submit, which cloudpickles it.
                payload = _sample_iso.fleche.bind(3)
                cloudpickle.dumps(payload)  # -> TypeError: cannot pickle '_thread.lock'
    finally:
        cloudpickle.unregister_pickle_by_value(this_module)
