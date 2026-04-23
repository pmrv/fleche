import pytest
from fleche.storage import ValueMemory, CallMemory
from fleche.caches import Cache, FilteredCache, Rejected
from fleche.call import Call, QueryCall
from fleche import fleche, cache


def test_filter_by_name():
    c = Cache(ValueMemory({}), CallMemory({}))

    @fleche
    def foo(x):
        return x + 1

    @fleche
    def bar(x):
        return x * 2

    with cache(c):
        foo(1)
        foo(2)
        bar(3)

    foo_name = foo.__wrapped__.__qualname__
    bar_name = bar.__wrapped__.__qualname__

    # Filter only foo calls
    c_foo = c.filter(lambda call: call.name == foo_name)
    assert isinstance(c_foo, FilteredCache)

    assert len(list(c_foo.query(QueryCall(name=foo_name, arguments=None)))) == 2
    assert len(list(c_foo.query(QueryCall(name=bar_name, arguments=None)))) == 0

    # Check values
    assert c_foo.load(foo.fleche.digest(1)).result == 2
    assert c_foo.load(foo.fleche.digest(2)).result == 3
    with pytest.raises(KeyError):
        c_foo.load(bar.fleche.digest(3))


def test_filter_reflects_changes():
    c = Cache(ValueMemory({}), CallMemory({}))

    @fleche
    def foo(x):
        return x + 1

    foo_name = foo.__wrapped__.__qualname__
    c_foo = c.filter(lambda call: call.name == foo_name)

    with cache(c):
        foo(1)

    # View should reflect changes in original cache
    assert c_foo.load(foo.fleche.digest(1)).result == 2


def test_filter_with_template():
    c = Cache(ValueMemory({}), CallMemory({}))

    @fleche
    def foo(x):
        return x + 1

    @fleche
    def bar(x):
        return x * 2

    with cache(c):
        foo(1)
        foo(2)
        bar(3)

    # Filter using a QueryCall object as a template
    foo_name = foo.__wrapped__.__qualname__
    c_filtered = c.filter(QueryCall(name=foo_name, arguments=None))

    assert len(list(c_filtered.query(QueryCall(name=None, arguments=None)))) == 2
    assert c_filtered.load(foo.fleche.digest(1)).result == 2
    with pytest.raises(KeyError):
        c_filtered.load(bar.fleche.digest(3))


def test_filtered_cache_is_readonly():
    c = Cache(ValueMemory({}), CallMemory({}))
    c_filtered = c.filter(lambda call: True)
    with pytest.raises(Rejected):
        c_filtered.save(Call(name="test", arguments={}))
