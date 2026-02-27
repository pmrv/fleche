import pytest
from fleche.storage import Memory
from fleche.caches import Cache
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

    assert len(list(c_foo.query(Call(name='foo', arguments=None)))) == 2
    assert len(list(c_foo.query(Call(name='bar', arguments=None)))) == 0

    # Check values
    assert c_foo.load(foo.digest(1)).result == 2
    assert c_foo.load(foo.digest(2)).result == 3
    with pytest.raises(KeyError):
        c_foo.load(bar.digest(3))

def test_filter_composite_values():
    c = Cache(Memory({}), Memory({}))

    @fleche
    def make_complex(x):
        return {"a": [x, x+1], "b": x*2}

    with cache(c):
        make_complex(10)

    c_filtered = c.filter(lambda call: True) # Keep everything

    loaded = c_filtered.load(make_complex.digest(10))
    assert loaded.result == {"a": [10, 11], "b": 20}

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
        # Pass result of producer (which is [5, 5, 5])
        consumer(l_res)

    # Filter only consumer calls
    c_consumer = c.filter(lambda call: call.name == 'consumer')

    assert len(list(c_consumer.query(Call(name='consumer', arguments=None)))) == 1
    assert len(list(c_consumer.query(Call(name='producer', arguments=None)))) == 0

    # Check that consumer's argument is still valid in c_consumer
    # This means c_consumer must have the value for the list in its value storage.
    res = list(c_consumer.query(Call(name='consumer', arguments=None)))[0]
    assert res.arguments['l'] == [5, 5, 5]

def test_filter_by_result():
    c = Cache(Memory({}), Memory({}))

    @fleche
    def calc(x): return x * x

    with cache(c):
        calc(1)
        calc(2)
        calc(3)
        calc(4)

    # Filter only calls with result > 5
    # Since we use lazy=True in filter, c.result will trigger a load from the source cache
    c_large = c.filter(lambda call: call.result > 5)

    results = sorted([call.result for call in c_large.query(Call(name='calc', arguments=None))])
    assert results == [9, 16]
