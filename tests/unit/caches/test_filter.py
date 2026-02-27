import pytest
from fleche.storage import Memory
from fleche.caches import Cache, FilteredCache
from fleche.call import Call
from fleche import fleche, cache, D

def test_filter_by_name():
    c = Cache(Memory({}), Memory({}))

    @fleche
    def foo(x): return x + 1
    @fleche
    def bar(x): return x * 2

    with cache(c):
        foo(1)
        foo(2)
        bar(3)

    # Filter only foo calls
    c_foo = c.filter(lambda call: call.name == 'foo')
    assert isinstance(c_foo, FilteredCache)

    assert len(list(c_foo.query(Call(name='foo', arguments=None)))) == 2
    assert len(list(c_foo.query(Call(name='bar', arguments=None)))) == 0

    # Check values
    assert c_foo.load(foo.digest(1)).result == 2
    assert c_foo.load(foo.digest(2)).result == 3
    with pytest.raises(KeyError):
        c_foo.load(bar.digest(3))

def test_filter_reflects_changes():
    c = Cache(Memory({}), Memory({}))

    @fleche
    def foo(x): return x + 1

    c_foo = c.filter(lambda call: call.name == 'foo')

    with cache(c):
        foo(1)

    # View should reflect changes in original cache
    assert c_foo.load(foo.digest(1)).result == 2

def test_filter_with_digests():
    c = Cache(Memory({}), Memory({}))

    @fleche
    def producer(x):
        return [x] * 3

    @fleche
    def consumer(l):
        return sum(l)

    with cache(c):
        l_res = producer(5)
        l_digest = producer.digest(5)
        consumer(l_res)

    # Filter only consumer calls
    c_consumer = c.filter(lambda call: call.name == 'consumer')

    assert len(list(c_consumer.query(Call(name='consumer', arguments=None)))) == 1
    assert len(list(c_consumer.query(Call(name='producer', arguments=None)))) == 0

    # Values should still be loadable because FilteredCache refers to original cache
    res = list(c_consumer.query(Call(name='consumer', arguments=None)))[0]
    assert res.arguments['l'] == [5, 5, 5]

def test_lazy_call_to_call():
    c = Cache(Memory({}), Memory({}))
    @fleche
    def foo(x): return x + 1

    with cache(c):
        foo(1)

    lc = c.load(foo.digest(1), lazy=True)
    full_call = lc.to_call()

    assert isinstance(full_call, Call)
    assert full_call.name == "foo"
    assert full_call.arguments == {"x": 1}
    assert full_call.result == 2

def test_filter_on_cache_stack():
    c1 = Cache(Memory({}), Memory({}))
    c2 = Cache(Memory({}), Memory({}))
    stack = c1.push(c2)

    @fleche
    def foo(x): return x + 1

    with cache(c1):
        foo(1)
    with cache(c2):
        foo(2)

    c_filtered = stack.filter(lambda call: call.arguments['x'] == 1)

    # Should find call from c1
    assert c_filtered.load(foo.digest(1)).result == 2
    # Should NOT find call from c2
    with pytest.raises(KeyError):
        c_filtered.load(foo.digest(2))

    # Test query
    results = list(c_filtered.query(Call(name='foo', arguments=None)))
    assert len(results) == 1
    assert results[0].arguments['x'] == 1
