import pytest
from fleche import fleche, cache, D
from fleche.caches import Cache
from fleche.digest import Digest
from fleche.storage import Memory
from unittest.mock import Mock


def test_positional_digest_expansion():
    c = Cache(Memory({}), Memory({}))

    @fleche
    def add(a, b):
        return a + b

    with cache(c):
        da = c.values.save(1)
        db = c.values.save(2)
        assert add(D(da), D(db)) == 3
        assert add(1, D(db)) == 3
        assert add(D(da), 2) == 3


def test_keyword_digest_expansion():
    c = Cache(Memory({}), Memory({}))

    @fleche
    def power(base, exp=1):
        return base**exp

    with cache(c):
        dbase = c.values.save(2)
        dexp = c.values.save(3)
        assert power(base=D(dbase), exp=D(dexp)) == 8
        assert power(D(dbase), exp=D(dexp)) == 8
        assert power(base=D(dbase), exp=3) == 8


def test_mixed_args_expansion():
    c = Cache(Memory({}), Memory({}))

    @fleche
    def mixed(a, b, c, d=None):
        return (a, b, c, d)

    with cache(c):
        da = c.values.save("a")
        dd = c.values.save("d")
        assert mixed(D(da), "b", c="c", d=D(dd)) == ("a", "b", "c", "d")


def test_expansion_failure_raises_keyerror():
    c = Cache(Memory({}), Memory({}))

    @fleche
    def func(x):
        return x

    with cache(c):
        with pytest.raises(KeyError):
            func(D("a" * 64))


def test_non_recursive_expansion_revisited():
    c = Cache(Memory({}), Memory({}))

    mock_func = Mock(side_effect=lambda x: x)

    @fleche
    def func(x):
        return mock_func(x)

    with cache(c):
        val = {"inner": 1}
        d_inner = c.values.save(val)

        # Immediate digest is expanded
        assert func(D(d_inner)) == val
        assert mock_func.call_count == 1
        args, _ = mock_func.call_args
        assert args[0] == val  # Expanded

        # Nested digest is NOT expanded in the call
        mock_func.reset_mock()
        nested = [D(d_inner)]
        res = func(nested)
        assert mock_func.call_count == 1
        args, _ = mock_func.call_args
        assert isinstance(args[0][0], Digest)  # NOT expanded
        assert args[0][0] == d_inner


def test_method_digest_expansion():
    class MyClass:
        def __init__(self, val):
            self.val = val

        def __digest__(self):
            return Digest(str(self.val))

        @fleche
        def add(self, x):
            return self.val + x

    c = Cache(Memory({}), Memory({}))
    with cache(c):
        obj = MyClass(10)
        dx = c.values.save(5)
        assert obj.add(D(dx)) == 15

def test_digested_args_are_not_saved():
    '''Regression test where previously we would accidentaly expand the digests too late, so that the functions run
    correctly, but are entered into the call storage as having received the literal digest as an input rather than the
    value.'''

    c = Cache(Memory({}), Memory({}))

    @fleche
    def func(x):
        return x

    with cache(c):
        value_key = c.values.save(4)
        func(value_key)
        key_with_digest = func.digest(value_key)
        key_with_value = func.digest(4)

        assert key_with_digest == key_with_value
        assert not isinstance(c.load(key_with_digest).arguments["x"], Digest)

def test_short_digest_expansion_via_D():
    # If the storage supports expansion of short digests, D(short) should also work
    # if it's eventually passed to storage.load
    c = Cache(Memory({}), Memory({}))

    @fleche
    def func(x):
        return x

    with cache(c):
        val = 12345
        full_d = c.values.save(val)
        short_d = full_d[:8]

        # Cache.load_value calls values.load(key)
        # Memory.load(key) calls self.expand(key) if len(key) < DIGEST_LENGTH
        assert func(D(short_d)) == val


def test_D_alias():
    assert D("abc") == Digest("abc")
    assert isinstance(D("abc"), Digest)
