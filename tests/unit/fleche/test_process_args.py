from typing import Annotated
from fleche.wrapper import process_ignore_required_args, ArgumentPolicy, Ignored, Required


def test_process_explicit_none():
    def func(a, b):
        pass

    policy = process_ignore_required_args(func, ignore=None, require=None)
    assert isinstance(policy, ArgumentPolicy)
    assert policy.ignored == frozenset()
    assert policy.required == frozenset()


def test_process_explicit_str():
    def func(a, b):
        pass

    policy = process_ignore_required_args(func, ignore="a", require="b")
    assert policy.ignored == frozenset({"a"})
    assert policy.required == frozenset({"b"})


def test_process_explicit_iterable():
    def func(a, b, c, d):
        pass

    policy = process_ignore_required_args(
        func, ignore=["a", "b"], require=("c", "d")
    )
    assert policy.ignored == frozenset({"a", "b"})
    assert policy.required == frozenset({"c", "d"})


def test_process_type_hints():
    def func(a: Ignored, b: Required):
        pass

    policy = process_ignore_required_args(func)
    assert "a" in policy.ignored
    assert "b" in policy.required


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

    policy = process_ignore_required_args(func, ignore="c", require="d")
    assert policy.ignored == frozenset({"a", "c"})
    assert policy.required == frozenset({"b", "d"})


def test_process_missing_hints():
    def func(a, b):
        pass

    # Deliberately remove __annotations__ to test the try-except block
    del func.__annotations__
    policy = process_ignore_required_args(func)
    assert policy.ignored == frozenset()
    assert policy.required == frozenset()


def test_process_invalid_signature():
    # Some objects might not have a signature
    policy = process_ignore_required_args(object(), require="a")
    assert policy.ignored == frozenset()
    assert policy.required == frozenset({"a"})


def test_process_annotated_type_hints():
    def func(a: Annotated[int, Ignored], b: Annotated[str, Required]):
        pass

    policy = process_ignore_required_args(func)
    assert "a" in policy.ignored
    assert "b" in policy.required


def test_process_generic_type_hints():
    def func(a: Ignored[int], b: Required[str]):
        pass

    policy = process_ignore_required_args(func)
    assert "a" in policy.ignored
    assert "b" in policy.required


def test_strip_for_key():
    policy = ArgumentPolicy(ignored=frozenset({"a", "b"}), required=frozenset())
    bound = {"a": 1, "b": 2, "c": 3}
    policy.strip_for_key(bound)
    assert bound == {"c": 3}


def test_check_required_all_present():
    def func(x, y=0):
        pass

    policy = ArgumentPolicy(ignored=frozenset(), required=frozenset({"x"}))
    assert policy.check_required(func, (), {"x": 1}) == []


def test_check_required_missing():
    def func(x=0, y=0):
        pass

    policy = ArgumentPolicy(ignored=frozenset(), required=frozenset({"x"}))
    missing = policy.check_required(func, (), {})
    assert "x" in missing


def test_check_required_empty():
    def func(x=0):
        pass

    policy = ArgumentPolicy(ignored=frozenset(), required=frozenset())
    assert policy.check_required(func, (1,), {}) == []
