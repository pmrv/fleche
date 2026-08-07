"""Unit tests for :mod:`fleche.executor`.

The integration suite (``tests/integration/test_parallel_execution.py``)
already exercises :func:`~fleche.executor.wrap_executor` end-to-end through
real thread and process pools, but the module's own control flow — the
``_is_fleche_function`` detection, the ``_split_submit_kwargs`` partition
(both the happy path and the ``inspect.signature`` fallback), and the
already-wrapped shortcut in :func:`wrap_executor` — was not covered by any
unit-level test.  These tests drive the module in isolation with in-process
stubs so the branches are exercised without paying the cost of a subprocess
spin-up.
"""

from concurrent.futures import Future
from types import SimpleNamespace
from unittest.mock import patch

import pytest

import fleche
from fleche import BoundWrapper, cache, wrap_executor
from fleche.caches import Cache
from fleche.executor import _is_fleche_function, _split_submit_kwargs
from fleche.storage import CallMemory, ValueMemory


# ---------------------------------------------------------------------------
# _is_fleche_function
# ---------------------------------------------------------------------------


class TestIsFlecheFunction:
    """A callable is 'fleche' iff its ``.fleche`` attribute is a SimpleNamespace.

    The predicate is the wrapper's discriminator between fleche-decorated
    functions (which own a ``fleche`` :class:`~types.SimpleNamespace` helper
    bundle) and everything else (plain functions, BoundWrappers, arbitrary
    callables).  A false positive here would send a non-fleche callable
    through the cache-hit branch and try to call ``func.fleche.contains(...)``
    on it.
    """

    def test_plain_callable_is_not_fleche(self):
        assert _is_fleche_function(lambda x: x) is False

    def test_fleche_decorated_callable_is_fleche(self):
        @fleche.fleche
        def f(x):
            return x

        assert _is_fleche_function(f) is True

    def test_attribute_named_fleche_that_is_not_a_namespace_is_not_fleche(self):
        """The check is ``isinstance(..., SimpleNamespace)``, not truthiness.

        A user object that happens to carry a ``.fleche`` string, dict, or
        module attribute must not be mistaken for a decorated function.
        """
        obj = SimpleNamespace()
        obj.fleche = "definitely not a namespace"  # type: ignore[attr-defined]
        assert _is_fleche_function(obj) is False


# ---------------------------------------------------------------------------
# _split_submit_kwargs
# ---------------------------------------------------------------------------


class TestSplitSubmitKwargs:
    """Kwargs declared keyword-only on ``submit`` are reserved for the executor.

    The wrapper needs to forward executor-reserved parameters (e.g. an HPC
    executor's ``resources=`` or ``resource_dict=``) to the underlying
    ``submit`` while binding everything else into the function payload.
    Stdlib ``concurrent.futures.Executor.submit`` has no keyword-only
    parameters, so for those executors this is a pure pass-through.
    """

    def test_all_kwargs_go_to_function_when_submit_has_no_keyword_only(self):
        def submit(fn, *args, **kwargs):
            pass

        for_submit, for_func = _split_submit_kwargs(
            submit, {"a": 1, "b": 2}
        )
        assert for_submit == {}
        assert for_func == {"a": 1, "b": 2}

    def test_keyword_only_params_are_split_off(self):
        def submit(fn, *args, resources=None, **kwargs):
            pass

        for_submit, for_func = _split_submit_kwargs(
            submit, {"resources": {"cores": 4}, "x": 42}
        )
        assert for_submit == {"resources": {"cores": 4}}
        assert for_func == {"x": 42}

    def test_empty_kwargs_returns_empty_partition(self):
        def submit(fn, *args, resources=None, **kwargs):
            pass

        for_submit, for_func = _split_submit_kwargs(submit, {})
        assert for_submit == {}
        assert for_func == {}

    def test_unparseable_signature_defers_all_kwargs_to_function(self):
        """When ``inspect.signature`` raises, everything goes to the payload.

        Some callables (certain C-level builtins, or objects with a broken
        ``__signature__``) refuse introspection.  In that case the wrapper
        conservatively assumes there are no executor-reserved kwargs and
        forwards every kwarg to the callable — the executor's own layer will
        surface an unknown-argument error if that assumption is wrong.
        """
        def submit(fn, *args, **kwargs):
            pass

        # Force the try/except branch by making signature() itself raise.
        with patch(
            "fleche.executor.signature", side_effect=TypeError("no signature")
        ):
            for_submit, for_func = _split_submit_kwargs(
                submit, {"a": 1, "resources": {"cores": 4}}
            )
        assert for_submit == {}
        assert for_func == {"a": 1, "resources": {"cores": 4}}


# ---------------------------------------------------------------------------
# wrap_executor
# ---------------------------------------------------------------------------


class _StubExecutor:
    """Minimal executor whose ``submit`` records the callable and args.

    ``submit`` runs the callable synchronously and returns an already-
    completed Future — enough to observe how :func:`wrap_executor`
    reshapes what the underlying executor sees, without spinning up a
    real pool.
    """

    def __init__(self):
        self.calls = []

    def submit(self, func, *args, **kwargs):
        self.calls.append((func, args, kwargs))
        fut = Future()
        fut.set_result(func(*args, **kwargs))
        return fut


class _NeverSubmitExecutor:
    """Executor stub that raises if ``submit`` is called.

    Used to prove that a cache-hit branch skips the underlying executor
    entirely; any call is an unambiguous test failure.
    """

    def submit(self, func, *args, **kwargs):
        raise AssertionError(
            f"submit unexpectedly reached (func={func!r}, args={args}, "
            f"kwargs={kwargs})"
        )


class _KeywordOnlyExecutor:
    """Executor whose ``submit`` declares a keyword-only ``resources``.

    Models the HPC-executor shape (executorlib, dask): callers pass
    executor-reserved parameters alongside function payload kwargs, and
    :func:`wrap_executor` must partition them so the reserved ones reach
    ``submit`` and the payload ones reach the callable.
    """

    def __init__(self):
        self.func = None
        self.submit_kwargs = None
        self.call_args = None
        self.call_kwargs = None

    def submit(self, func, *args, resources=None, **kwargs):
        self.func = func
        self.submit_kwargs = {"resources": resources, **kwargs}
        self.call_args = args
        self.call_kwargs = kwargs
        fut = Future()
        fut.set_result(func(*args, **kwargs))
        return fut


class TestWrapExecutor:
    """``wrap_executor`` monkey-patches ``submit`` in-place with our shim."""

    def test_returns_the_same_executor_instance(self):
        """The patched executor is the same object; we mutate, not wrap.

        Callers keep any reference they held before the patch, so returning
        a wrapper object would silently divide the world into 'patched
        reference' and 'unpatched reference'.
        """
        executor = _StubExecutor()
        assert wrap_executor(executor) is executor

    def test_patched_submit_carries_wrapped_marker(self):
        """The patched ``submit`` carries ``_fleche_wrapped=True``.

        The marker is how the idempotency check in the next call recognises
        an already-patched executor — losing it would silently stack a second
        interception layer on top of the first.
        """
        executor = _StubExecutor()
        original_submit = executor.submit
        assert not getattr(original_submit, "_fleche_wrapped", False)

        wrap_executor(executor)
        assert getattr(executor.submit, "_fleche_wrapped", False) is True

    def test_second_wrap_is_a_no_op(self):
        """Wrapping an already-wrapped executor returns without re-patching.

        Without this shortcut a second wrap would layer a fresh interception
        closure over the previous one, doubling the ``bind`` cost per submit
        and — because the outer layer would re-bind the already-bound inner
        callable — subtly changing observable behaviour.
        """
        executor = _StubExecutor()
        wrap_executor(executor)
        patched_once = executor.submit
        wrap_executor(executor)
        assert executor.submit is patched_once

    def test_non_fleche_callable_is_bound_before_submission(self):
        """Plain callables are wrapped in a ``BoundWrapper`` before submit.

        The active cache/metadata state has to travel with the callable to
        the worker; without this bind, a plain function nested-calling a
        fleche-decorated one inside a subprocess would see an empty default
        cache instead of the one active in the parent (regression #691).
        """
        executor = _StubExecutor()
        wrap_executor(executor)

        def plain(x):
            return x + 1

        fut = executor.submit(plain, 41)
        assert fut.result() == 42
        submitted_func, args, _ = executor.calls[-1]
        assert isinstance(submitted_func, BoundWrapper)
        assert submitted_func.func is plain
        assert args == (41,)

    def test_already_bound_wrapper_is_forwarded_as_is(self):
        """An already-bound ``BoundWrapper`` must not be double-bound.

        ``BoundWrapper`` is idempotent under the wrap-executor bind because
        the outer bind would freeze the *inner* wrapper's captured cache
        rather than the current one; short-circuiting on ``isinstance`` keeps
        the caller's explicit binding authoritative (PR #724).
        """
        cache1 = Cache(ValueMemory({}), CallMemory({}))
        with cache(cache1):
            bound = BoundWrapper.bind(lambda x: x * 2)

        executor = _StubExecutor()
        wrap_executor(executor)
        fut = executor.submit(bound, 5)
        assert fut.result() == 10
        submitted_func, _, _ = executor.calls[-1]
        assert submitted_func is bound

    def test_cache_hit_returns_completed_future_without_calling_submit(self):
        """Cache hits skip the executor entirely.

        The point of caching is to avoid the work — and for an executor
        wrapper, the submit round-trip itself is part of that work.  This
        pins the short-circuit: a hit yields a pre-completed
        :class:`~concurrent.futures.Future` and the underlying ``submit`` is
        never touched (``_NeverSubmitExecutor`` asserts on any call).
        """
        @fleche.fleche
        def add(a, b):
            return a + b

        cache1 = Cache(ValueMemory({}), CallMemory({}))
        with cache(cache1):
            add(2, 3)  # seed the cache

            executor = _NeverSubmitExecutor()
            wrap_executor(executor)
            fut = executor.submit(add, 2, 3)

        assert fut.done()
        assert fut.result() == 5

    def test_cache_miss_binds_and_submits(self):
        """A cache miss binds the callable and forwards it to ``submit``.

        The submitted object must be a :class:`BoundWrapper` (so the worker
        restores the right cache) whose ``func`` is a ``functools.partial``
        pre-applying the miss's arguments.
        """
        import functools

        @fleche.fleche
        def add(a, b):
            return a + b

        cache1 = Cache(ValueMemory({}), CallMemory({}))
        executor = _StubExecutor()
        with cache(cache1):
            wrap_executor(executor)
            fut = executor.submit(add, 7, 8)

        assert fut.result() == 15
        submitted_func, args, kwargs = executor.calls[-1]
        # The wrapper baked (7, 8) into a partial and bound the closure,
        # so nothing is left in *args / **kwargs at submit time.
        assert isinstance(submitted_func, BoundWrapper)
        assert isinstance(submitted_func.func, functools.partial)
        assert args == ()
        assert kwargs == {}
        # And the miss should have populated the cache.
        assert cache1.contains(add.digest(7, 8))

    def test_executor_reserved_kwargs_are_split_from_payload(self):
        """Keyword-only params on ``submit`` go to the executor, not the callable.

        ``_KeywordOnlyExecutor.submit`` declares ``resources`` as
        keyword-only; the caller passes both ``resources={'cores': 4}`` and
        the function-argument ``a=3``.  The wrapper must route ``resources``
        to ``submit`` and bake ``a`` into the function payload.
        """
        @fleche.fleche
        def add(a, b):
            return a + b

        cache1 = Cache(ValueMemory({}), CallMemory({}))
        executor = _KeywordOnlyExecutor()
        with cache(cache1):
            wrap_executor(executor)
            fut = executor.submit(add, resources={"cores": 4}, a=1, b=2)

        assert fut.result() == 3
        assert executor.submit_kwargs == {"resources": {"cores": 4}}
        # The BoundWrapper has (a=1, b=2) baked in via functools.partial,
        # so the stub's underlying call sees no leftover args/kwargs.
        assert executor.call_args == ()
        assert executor.call_kwargs == {}
