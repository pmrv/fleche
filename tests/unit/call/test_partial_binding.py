import pytest
from inspect import signature
from fleche.call import QueryCall


def func_simple(a, b):
    pass


def func_args(a, *args):
    pass


def func_kwargs(a, **kwargs):
    pass


def func_kwonly(a, *, b):
    pass


def func_posonly(a, /, b):
    pass


def func_defaults(a=1, b=2):
    pass


def test_simple_partial():
    call = QueryCall.from_call(func_simple, 1)
    assert call.arguments == {"a": 1, "b": None}


def test_simple_partial_keyword():
    call = QueryCall.from_call(func_simple, b=2)
    assert call.arguments == {"a": None, "b": 2}


def test_simple_full():
    call = QueryCall.from_call(func_simple, 1, 2)
    assert call.arguments == {"a": 1, "b": 2}


def test_args_partial():
    call = QueryCall.from_call(func_args, 1)
    # *args defaults to empty tuple with apply_defaults()
    assert call.arguments == {"a": 1, "args": ()}


def test_args_partial_with_values():
    call = QueryCall.from_call(func_args, 1, 2, 3)
    assert call.arguments == {"a": 1, "args": (2, 3)}


def test_kwargs_partial():
    call = QueryCall.from_call(func_kwargs, 1)
    # **kwargs defaults to empty dict with apply_defaults()
    assert call.arguments == {"a": 1, "kwargs": {}}


def test_kwargs_partial_with_values():
    call = QueryCall.from_call(func_kwargs, 1, x=2)
    assert call.arguments == {"a": 1, "kwargs": {"x": 2}}


def test_kwonly_partial():
    call = QueryCall.from_call(func_kwonly, 1)
    assert call.arguments == {"a": 1, "b": None}


def test_kwonly_partial_with_values():
    call = QueryCall.from_call(func_kwonly, 1, b=2)
    assert call.arguments == {"a": 1, "b": 2}


def test_posonly_partial():
    call = QueryCall.from_call(func_posonly, 1)
    assert call.arguments == {"a": 1, "b": None}


def test_posonly_partial_with_values():
    call = QueryCall.from_call(func_posonly, 1, 2)
    assert call.arguments == {"a": 1, "b": 2}


def test_defaults_partial():
    # Verify that defaults ARE applied even when partial=True.
    call = QueryCall.from_call(func_defaults)
    assert call.arguments == {"a": 1, "b": 2}


def test_defaults_full():
    # Verify that defaults ARE applied when partial=False (default behavior).
    call = QueryCall.from_call(func_defaults)
    assert call.arguments == {"a": 1, "b": 2}


def test_defaults_partial_explicit():
    # If explicitly passed, overrides default
    call = QueryCall.from_call(func_defaults, a=10)
    assert call.arguments == {"a": 10, "b": 2}


def test_defaults_partial_explicit_none():
    # If explicitly passed None, it overrides default (wildcard behavior)
    call = QueryCall.from_call(func_defaults, b=None)
    assert call.arguments == {"a": 1, "b": None}
