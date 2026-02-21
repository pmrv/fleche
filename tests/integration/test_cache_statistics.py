
import pytest
from fleche import fleche, cache
from fleche.storage.memory import Memory
from fleche.storage.sql import Sql
from fleche.caches import Cache, CacheStack

def test_cache_stats_basic():
    val_storage = Memory({})
    call_storage = Memory({})
    c = Cache(values=val_storage, calls=call_storage)

    with cache(c):
        @fleche
        def func(x):
            return x * 2

        key = func.digest(10)

        # Miss
        func(10)
        stats = c.calls.load(key).stats
        assert stats.misses == 1
        assert stats.hits == 0

        # Hit
        func(10)
        stats = c.calls.load(key).stats
        assert stats.misses == 1
        assert stats.hits == 1

def test_cache_stats_sql(tmp_path):
    db_path = tmp_path / "test.db"
    val_storage = Memory({})
    call_storage = Sql(url=str(db_path))
    c = Cache(values=val_storage, calls=call_storage)

    with cache(c):
        @fleche
        def func(x):
            return x * 2

        key = func.digest(10)

        func(10)
        stats = c.calls.load(key).stats
        assert stats.misses == 1
        assert stats.hits == 0

        func(10)
        stats = c.calls.load(key).stats
        assert stats.misses == 1
        assert stats.hits == 1

def test_cache_stats_stack():
    # Bottom cache
    c1 = Cache(values=Memory({}), calls=Memory({}))
    # Top cache
    c2 = Cache(values=Memory({}), calls=Memory({}))

    stack = CacheStack((c1, c2))

    with cache(stack):
        @fleche
        def func(x):
            return x * 2

        key = func.digest(5)

        # Initial call - saves to c1 (bottom)
        func(5)

        assert c1.calls.load(key).stats.misses == 1
        assert c1.calls.load(key).stats.hits == 0
        with pytest.raises(KeyError):
            c2.calls.load(key)

        # Second call - hit in c1
        func(5)
        assert c1.calls.load(key).stats.hits == 1

        # Manually move to c2
        call_obj = c1.calls.load(key)
        c2.save(call_obj) # This increments misses in c2
        assert c2.calls.load(key).stats.misses == 1

        # Now call again. stack.load should find it in c1 first if we didn't change the order.
        # Wait, CacheStack((c1, c2)) -> c1 is stack[0], c2 is stack[1].
        # load tries stack[0] then stack[1].

        func(5)
        assert c1.calls.load(key).stats.hits == 2
        assert c2.calls.load(key).stats.hits == 0 # c2 not reached

        # Reverse stack
        stack_rev = CacheStack((c2, c1))
        with cache(stack_rev):
            func(5)
            assert c2.calls.load(key).stats.hits == 1
            assert c1.calls.load(key).stats.hits == 2 # unchanged

def test_key_stability_with_digests():
    from fleche.digest import digest
    from fleche.call import Call, Statistics

    def my_func(x):
        return x * 2

    # Scenario 1: Decorator before save
    c1 = Call.from_call(my_func, 2)
    # fleche decorator sets code_digest to None by default
    c1.code_digest = None
    k1 = c1.to_lookup_key()

    # Scenario 2: Inside Cache.save
    # result and arguments are digested
    res_digest = digest(4)
    arg_digest = digest(2)
    c2 = Call(name="my_func", arguments={"x": arg_digest}, result=res_digest, module=c1.module, version=c1.version)
    c2.code_digest = None
    k2 = c2.to_lookup_key()

    assert k1 == k2, "Key should be stable even after arguments are converted to Digests"

    # Scenario 3: With different stats
    c3 = Call(name="my_func", arguments={"x": arg_digest}, result=res_digest,
              module=c1.module, version=c1.version,
              stats=Statistics(hits=100, misses=50))
    c3.code_digest = None
    k3 = c3.to_lookup_key()

    assert k1 == k3, "Key should be stable regardless of statistics values"
