"""Executor wrapper that intercepts ``submit`` for fleche-decorated functions.

Motivation: users passing a :func:`fleche.fleche`-decorated function to
``executor.submit(...)`` have to remember to call :meth:`.BoundWrapper.bind`
themselves to carry the active cache/metadata state into the worker.  They also
pay the submit/serialisation cost even when the result is already cached.  The
same problem affects plain (non-fleche) callables that merely *call* a
fleche-decorated function somewhere in their body: unless they are bound too,
the active cache/metadata state never reaches the worker process.

:func:`wrap_executor` patches the ``submit`` method of an executor *instance*
(we cannot subclass, since callers pass us instances of third-party executors)
so that:

* non-fleche callables are bound via :meth:`.BoundWrapper.bind` and submitted
  to the original ``submit`` unchanged otherwise, so that any fleche calls
  nested inside them still see the active cache/metadata state (a callable
  that is already a :class:`.BoundWrapper` is submitted as-is, since it is
  already bound),
* fleche callables whose result is already cached are returned via an
  already-completed :class:`~concurrent.futures.Future` without touching the
  executor, and
* otherwise the call is bound via :meth:`.BoundWrapper.bind` and submitted to
  the original ``submit``.

Executors that declare their own keyword-only parameters on ``submit``
(e.g. ``resources=`` or ``resource_dict=``) have those split off from the
caller's ``**kwargs`` and forwarded to the underlying ``submit`` while the
remaining keyword arguments are bound as part of the function payload.
"""

from concurrent.futures import Future
from inspect import signature, Parameter
from types import SimpleNamespace

from . import state


__all__ = ["wrap_executor"]


def _is_fleche_function(func) -> bool:
    return isinstance(getattr(func, "fleche", None), SimpleNamespace)


def _split_submit_kwargs(submit_method, kwargs):
    """Partition ``kwargs`` into (executor-reserved, function-payload).

    Any keyword-only parameter declared on ``submit_method``'s signature is
    reserved for the executor; everything else (including arguments matched by
    a ``**kwargs`` catch-all) is forwarded to the callable.
    ``concurrent.futures.Executor.submit`` has no keyword-only parameters, so
    for stdlib executors this is a pure pass-through.
    """
    try:
        sig = signature(submit_method)
    except (TypeError, ValueError):
        return {}, dict(kwargs)
    submit_only = {
        name for name, p in sig.parameters.items()
        if p.kind is Parameter.KEYWORD_ONLY
    }
    for_submit, for_func = {}, {}
    for k, v in kwargs.items():
        if k in submit_only:
            for_submit[k] = v
        else:
            for_func[k] = v
    return for_submit, for_func


def wrap_executor(executor):
    """Monkey-patch ``executor.submit`` to intercept fleche-wrapped functions.

    Calling :func:`wrap_executor` on an executor that is already wrapped is a
    no-op: the patch is not stacked, and the original ``submit`` continues to
    refer to the pre-wrap method.

    Args:
        executor: any object with a ``submit(func, *args, **kwargs)`` method
            (e.g. :class:`concurrent.futures.Executor` subclass instances).

    Returns:
        The same ``executor`` instance, with a replaced ``submit`` attribute.
    """
    original_submit = executor.submit
    if getattr(original_submit, "_fleche_wrapped", False):
        return executor

    def submit(func, *args, **kwargs):
        if not _is_fleche_function(func):
            if not isinstance(func, state.BoundWrapper):
                func = state.BoundWrapper.bind(func)
            return original_submit(func, *args, **kwargs)

        submit_kwargs, func_kwargs = _split_submit_kwargs(
            original_submit, kwargs
        )

        if func.fleche.contains(*args, **func_kwargs):
            fut: Future = Future()
            fut.set_result(func.fleche.load(*args, **func_kwargs))
            return fut

        bound = func.fleche.bind(*args, **func_kwargs)
        return original_submit(bound, **submit_kwargs)

    submit._fleche_wrapped = True  # type: ignore
    executor.submit = submit
    return executor
