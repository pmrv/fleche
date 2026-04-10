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
    # *args not supplied → None (wildcard)
    assert call.arguments == {"a": 1, "args": None}


def test_args_partial_with_values():
    call = QueryCall.from_call(func_args, 1, 2, 3)
    assert call.arguments == {"a": 1, "args": (2, 3)}


def test_kwargs_partial():
    call = QueryCall.from_call(func_kwargs, 1)
    # **kwargs not supplied → None (wildcard)
    assert call.arguments == {"a": 1, "kwargs": None}


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


def test_defaults_not_specified():
    # Unspecified args are None (wildcard), defaults are NOT applied.
    call = QueryCall.from_call(func_defaults)
    assert call.arguments == {"a": None, "b": None}


def test_defaults_partial_explicit():
    # If explicitly passed, the value is used; unspecified args remain None (wildcard)
    call = QueryCall.from_call(func_defaults, a=10)
    assert call.arguments == {"a": 10, "b": None}


def test_defaults_partial_explicit_none():
    # Explicitly passing None is still None (wildcard)
    call = QueryCall.from_call(func_defaults, b=None)
    assert call.arguments == {"a": None, "b": None}
