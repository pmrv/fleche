"""Regression test for issue #840.

https://github.com/pmrv/fleche/issues/840

``BoundWrapper`` only survived a ``ProcessPoolExecutor`` under the ``fork``
start method. Under ``spawn``/``forkserver`` the worker is a fresh
interpreter that imports ``__main__`` (or the submitting module) to resolve
a pickled function by reference; a function that isn't reachable that way —
defined in ``__main__``, a notebook, or (as reproduced here) a local
closure — made the default pickling of ``BoundWrapper`` fail, bringing the
whole pool down as ``BrokenProcessPool``.

``BoundWrapper.__reduce__`` now falls back to serialising the wrapped
function by value with cloudpickle whenever plain pickle can't reference it,
regardless of which pickler the carrier (here, stdlib ``pickle`` via
``ProcessPoolExecutor``) uses.
"""

import concurrent.futures
import multiprocessing as mp

import pytest

import fleche
from fleche.caches import Cache
from fleche.state import BoundWrapper
from fleche.storage import ValueMemory, CallMemory


def test_bound_wrapper_survives_spawn_process_pool_executor():
    cloudpickle = pytest.importorskip("cloudpickle")

    # A local closure is never importable by reference — same shape as a
    # __main__- or notebook-defined function, which is what actually bites
    # users on macOS/Windows (spawn) and Linux 3.14+ (forkserver default).
    def local_only(x):
        return x * x

    # Preflight: some cloudpickle/Python combinations can't round-trip even
    # a bare closure by value (e.g. cloudpickle 2.0's bytecode walk vs newer
    # Python code-object layouts — the same environment gap
    # test_wrap_executor_cloudpickle_lock.py already skips around). Check in
    # this process, with the same cloudpickle the spawned worker will use,
    # so that failure doesn't surface as an opaque BrokenProcessPool.
    try:
        cloudpickle.loads(cloudpickle.dumps(local_only))(0)
    except Exception as exc:
        pytest.skip(f"cloudpickle by-value unsupported in this env: {exc!r}")

    with fleche.cache(Cache(ValueMemory({}), CallMemory({}))):
        bound = BoundWrapper.bind(local_only)

    ctx = mp.get_context("spawn")
    with concurrent.futures.ProcessPoolExecutor(
        max_workers=1, mp_context=ctx
    ) as pool:
        results = list(pool.map(bound, range(5)))

    assert results == [0, 1, 4, 9, 16]
