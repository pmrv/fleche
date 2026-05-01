from typing import Annotated
from fleche.call import FunctionProfile
from fleche.wrapper import process_ignore_required_args, Ignored, Required


def test_process_explicit_none():
    def func(a, b):
        pass

    profile = process_ignore_required_args(func, ignore=None, require=None)
    assert isinstance(profile, FunctionProfile)
    assert profile.ignored == frozenset()
    assert profile.required == frozenset()


def test_process_explicit_str():
    def func(a, b):
        pass

    profile = process_ignore_required_args(func, ignore="a", require="b")
    assert profile.ignored == frozenset({"a"})
    assert profile.required == frozenset({"b"})


def test_process_explicit_iterable():
    def func(a, b, c, d):
        pass

    profile = process_ignore_required_args(
        func, ignore=["a", "b"], require=("c", "d")
    )
    assert profile.ignored == frozenset({"a", "b"})
    assert profile.required == frozenset({"c", "d"})


def test_process_type_hints():
    def func(a: Ignored, b: Required):
        pass

    profile = process_ignore_required_args(func)
    assert "a" in profile.ignored
    assert "b" in profile.required


def test_process_positional_only_required_warning(caplog):
    def func(a: Required, /):
        pass

    import logging

    with caplog.at_level(logging.WARNING):
        process_ignore_required_args(func)
        assert "is marked as Required but is positional-only" in caplog.text


def test_process_merge_hints_and_args():
    def func(a: Ignored, b: Required):
        pass

    profile = process_ignore_required_args(func, ignore="c", require="d")
    assert profile.ignored == frozenset({"a", "c"})
    assert profile.required == frozenset({"b", "d"})


def test_process_missing_hints():
    def func(a, b):
        pass

    # Deliberately remove __annotations__ to test the try-except block
    del func.__annotations__
    profile = process_ignore_required_args(func)
    assert profile.ignored == frozenset()
    assert profile.required == frozenset()


def test_process_invalid_signature():
    # Some objects might not have a signature
    profile = process_ignore_required_args(object(), require="a")
    assert profile.ignored == frozenset()
    assert profile.required == frozenset({"a"})


def test_process_annotated_type_hints():
    def func(a: Annotated[int, Ignored], b: Annotated[str, Required]):
        pass

    profile = process_ignore_required_args(func)
    assert "a" in profile.ignored
    assert "b" in profile.required


def test_process_generic_type_hints():
    def func(a: Ignored[int], b: Required[str]):
        pass

    profile = process_ignore_required_args(func)
    assert "a" in profile.ignored
    assert "b" in profile.required


def test_strip_for_key():
    def func(a, b, c):
        pass

    profile = process_ignore_required_args(func, ignore=["a", "b"])
    bound = {"a": 1, "b": 2, "c": 3}
    profile.strip_for_key(bound)
    assert bound == {"c": 3}


def test_check_required_all_present():
    def func(x, y=0):
        pass

    profile = process_ignore_required_args(func, require="x")
    assert profile.check_required((), {"x": 1}) == []


def test_check_required_missing():
    def func(x=0, y=0):
        pass

    profile = process_ignore_required_args(func, require="x")
    missing = profile.check_required((), {})
    assert "x" in missing


def test_check_required_empty():
    def func(x=0):
        pass

    profile = process_ignore_required_args(func)
    assert profile.check_required((1,), {}) == []
