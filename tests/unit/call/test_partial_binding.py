import pytest
from inspect import signature
from fleche.call import Call

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
    call = Call.from_call(func_simple, 1, partial=True)
    assert call.arguments == {'a': 1, 'b': None}

def test_simple_partial_keyword():
    call = Call.from_call(func_simple, b=2, partial=True)
    assert call.arguments == {'a': None, 'b': 2}

def test_simple_full():
    call = Call.from_call(func_simple, 1, 2, partial=False)
    assert call.arguments == {'a': 1, 'b': 2}

def test_args_partial():
    call = Call.from_call(func_args, 1, partial=True)
    # When partial=True, *args (VAR_POSITIONAL) is None if not provided? No, signature logic sets missing to None.
    # Let's verify what `sig.parameters` contains for *args. It contains 'args'.
    # `bound.arguments.get('args')` will return None if not present in partial bind?
    # Actually bind_partial will only populate what is passed. So if nothing passed for *args, it's not in bound.arguments.
    # Then `bound.arguments.get(name)` returns None.
    assert call.arguments == {'a': 1, 'args': None}

def test_args_partial_with_values():
    call = Call.from_call(func_args, 1, 2, 3, partial=True)
    assert call.arguments == {'a': 1, 'args': (2, 3)}

def test_kwargs_partial():
    call = Call.from_call(func_kwargs, 1, partial=True)
    # Similar logic for **kwargs (VAR_KEYWORD). If not present, get returns None.
    assert call.arguments == {'a': 1, 'kwargs': None}

def test_kwargs_partial_with_values():
    call = Call.from_call(func_kwargs, 1, x=2, partial=True)
    assert call.arguments == {'a': 1, 'kwargs': {'x': 2}}

def test_kwonly_partial():
    call = Call.from_call(func_kwonly, 1, partial=True)
    assert call.arguments == {'a': 1, 'b': None}

def test_kwonly_partial_with_values():
    call = Call.from_call(func_kwonly, 1, b=2, partial=True)
    assert call.arguments == {'a': 1, 'b': 2}

def test_posonly_partial():
    call = Call.from_call(func_posonly, 1, partial=True)
    assert call.arguments == {'a': 1, 'b': None}

def test_posonly_partial_with_values():
    call = Call.from_call(func_posonly, 1, 2, partial=True)
    assert call.arguments == {'a': 1, 'b': 2}

def test_defaults_partial():
    # Verify that defaults are NOT applied when partial=True.
    call = Call.from_call(func_defaults, partial=True)
    assert call.arguments == {'a': None, 'b': None}

def test_defaults_full():
    # Verify that defaults ARE applied when partial=False (default behavior).
    call = Call.from_call(func_defaults, partial=False)
    assert call.arguments == {'a': 1, 'b': 2}

def test_defaults_partial_explicit():
    call = Call.from_call(func_defaults, a=10, partial=True)
    assert call.arguments == {'a': 10, 'b': None}
