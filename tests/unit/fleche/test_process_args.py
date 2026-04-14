from typing import Annotated
from fleche.wrapper import process_ignore_required_args, Ignored, Required


def test_process_explicit_none():
    def func(a, b):
        pass

    ignored, required = process_ignore_required_args(func, ignore=None, require=None)
    assert ignored == ()
    assert required == ()


def test_process_explicit_str():
    def func(a, b):
        pass

    ignored, required = process_ignore_required_args(func, ignore="a", require="b")
    assert ignored == ("a",)
    assert required == ("b",)


def test_process_explicit_iterable():
    def func(a, b, c, d):
        pass

    ignored, required = process_ignore_required_args(
        func, ignore=["a", "b"], require=("c", "d")
    )
    assert ignored == ("a", "b")
    assert required == ("c", "d")


def test_process_type_hints():
    def func(a: Ignored, b: Required):
        pass

    ignored, required = process_ignore_required_args(func)
    assert "a" in ignored
    assert "b" in required



def test_process_merge_hints_and_args():
    def func(a: Ignored, b: Required):
        pass

    ignored, required = process_ignore_required_args(func, ignore="c", require="d")
    assert set(ignored) == {"a", "c"}
    assert set(required) == {"b", "d"}


def test_process_missing_hints():
    def func(a, b):
        pass

    # Deliberately remove __annotations__ to test the try-except block
    del func.__annotations__
    ignored, required = process_ignore_required_args(func)
    assert ignored == ()
    assert required == ()


def test_process_invalid_signature():
    # Some objects might not have a signature
    ignored, required = process_ignore_required_args(object(), require="a")
    assert ignored == ()
    assert required == ("a",)


def test_process_annotated_type_hints():
    def func(a: Annotated[int, Ignored], b: Annotated[str, Required]):
        pass

    ignored, required = process_ignore_required_args(func)
    assert "a" in ignored
    assert "b" in required


def test_process_generic_type_hints():
    def func(a: Ignored[int], b: Required[str]):
        pass

    ignored, required = process_ignore_required_args(func)
    assert "a" in ignored
    assert "b" in required
