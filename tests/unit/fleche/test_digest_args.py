import pytest
from fleche import fleche, cache, D
from fleche.caches import Cache
from fleche.digest import Digest
from fleche.storage import ValueMemory, CallMemory
from unittest.mock import Mock


def test_positional_digest_expansion():
    c = Cache(ValueMemory({}), CallMemory({}))

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
    c = Cache(ValueMemory({}), CallMemory({}))

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
    c = Cache(ValueMemory({}), CallMemory({}))

    @fleche
    def mixed(a, b, c, d=None):
        return (a, b, c, d)

    with cache(c):
        da = c.values.save("a")
        dd = c.values.save("d")
        assert mixed(D(da), "b", c="c", d=D(dd)) == ("a", "b", "c", "d")


def test_expansion_failure_raises_keyerror():
    c = Cache(ValueMemory({}), CallMemory({}))

    @fleche
    def func(x):
        return x

    with cache(c):
        with pytest.raises(KeyError):
            func(D("a" * 64))


def test_non_recursive_expansion_revisited():
    c = Cache(ValueMemory({}), CallMemory({}))

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
        func(nested)
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

    c = Cache(ValueMemory({}), CallMemory({}))
    with cache(c):
        obj = MyClass(10)
        dx = c.values.save(5)
        assert obj.add(D(dx)) == 15

def test_digested_args_are_not_saved():
    '''Regression test where previously we would accidentaly expand the digests too late, so that the functions run
    correctly, but are entered into the call storage as having received the literal digest as an input rather than the
    value.'''

    c = Cache(ValueMemory({}), CallMemory({}))

    @fleche
    def func(x):
        return x

    with cache(c):
        value_key = c.values.save(4)
        func(value_key)
        key_with_digest = func.fleche.digest(value_key)
        key_with_value = func.fleche.digest(4)

        assert key_with_digest == key_with_value
        assert not isinstance(c.load(key_with_digest).arguments["x"], Digest)

def test_short_digest_expansion_via_D():
    # If the storage supports expansion of short digests, D(short) should also work
    # if it's eventually passed to storage.load
    c = Cache(ValueMemory({}), CallMemory({}))

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


@pytest.mark.parametrize(
    "value",
    [
        42,                  # non-string
        "g" * 8,             # non-hex string (g is not a hex digit)
        "abc!",              # mixed hex + non-hex
        "",                  # empty string fails 0 < len
        "a" * 65,            # exceeds DIGEST_LENGTH
    ],
    ids=["int", "non_hex", "mixed", "empty", "too_long"],
)
def test_D_falls_through_to_digest_for_non_short_hex(value):
    """D() must compute the digest of any input that isn't a short hex string.

    Pins the documented contract: only non-empty hex strings up to
    DIGEST_LENGTH characters are used verbatim; anything else (non-strings,
    empty strings, non-hex characters, too-long strings) is hashed.
    """
    from fleche import digest as _digest

    result = D(value)
    assert isinstance(result, Digest)
    assert result == _digest.digest(value)
