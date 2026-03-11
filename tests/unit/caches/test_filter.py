import pytest
from fleche.storage import Memory
from fleche.caches import Cache, FilteredCache, Rejected
from fleche.call import Call
from fleche import fleche, cache


def test_filter_by_name():
    c = Cache(Memory({}), Memory({}))

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

    # Filter only foo calls
    c_foo = c.filter(lambda call: call.name == "foo")
    assert isinstance(c_foo, FilteredCache)

    assert len(list(c_foo.query(Call(name="foo", arguments=None)))) == 2
    assert len(list(c_foo.query(Call(name="bar", arguments=None)))) == 0

    # Check values
    assert c_foo.load(foo.digest(1)).result == 2
    assert c_foo.load(foo.digest(2)).result == 3
    with pytest.raises(KeyError):
        c_foo.load(bar.digest(3))


def test_filter_reflects_changes():
    c = Cache(Memory({}), Memory({}))

    @fleche
    def foo(x):
        return x + 1

    c_foo = c.filter(lambda call: call.name == "foo")

    with cache(c):
        foo(1)

    # View should reflect changes in original cache
    assert c_foo.load(foo.digest(1)).result == 2


def test_filter_with_template():
    c = Cache(Memory({}), Memory({}))

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

    # Filter using a Call object as a template
    c_filtered = c.filter(Call(name="foo", arguments=None))

    assert len(list(c_filtered.query(Call(name=None, arguments=None)))) == 2
    assert c_filtered.load(foo.digest(1)).result == 2
    with pytest.raises(KeyError):
        c_filtered.load(bar.digest(3))


def test_filtered_cache_is_readonly():
    c = Cache(Memory({}), Memory({}))
    c_filtered = c.filter(lambda call: True)
    with pytest.raises(Rejected):
        c_filtered.save(Call(name="test", arguments={}))
