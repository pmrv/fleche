"""Integration test: random kwargs through @fleche, then query via Cache.query and function.query."""

import random
import string

import hypothesis.strategies as st
from hypothesis import HealthCheck, assume, given, settings

from fleche import fleche, cache
from fleche.call import QueryCall

from tests.strategies import st_nested_values


# Strategy for valid Python-identifier keys mapped to nested values (incl. dataclasses)
_ident_key = st.text(
    alphabet=string.ascii_lowercase, min_size=1, max_size=8
).filter(lambda k: k != "metadata")  # 'metadata' is reserved by .query()

kwargs_strategy = st.dictionaries(
    _ident_key,
    st_nested_values,
    min_size=1,
    max_size=6,
)


@given(kwargs=kwargs_strategy)
@settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_fleche_cache_query_random_kwargs(cache_fixture, kwargs):
    """Cache.query and function.query(**kwargs) yield back a cached call.

    After calling the decorated function, verify that:
      1. ``function.query(**kwargs)`` returns the call (exact match).
      2. ``Cache.query`` with a name-only (wildcard) template returns the call.
      3. After deleting random keys from the kwargs, a wildcard query on
         ``Cache.query`` still yields the original call.
    """

    test_cache = cache_fixture

    @fleche
    def test(**kwargs):
        return kwargs

    with cache(test_cache):
        result = test(**kwargs)

        # --- 1. function.query with full kwargs: exact match ---------------
        matches = list(test.query(**kwargs))
        assert len(matches) >= 1, (
            f"function.query(**kwargs) should find the call; got {len(matches)}"
        )
        assert any(m.result == result for m in matches)

        # --- 2. Delete random keys, then query ----------------------------
        keys = list(kwargs.keys())
        n_delete = random.randint(1, len(keys))
        for k in random.sample(keys, n_delete):
            del kwargs[k]

        # The stored call is untouched; a fully wildcarded query must
        # still return it.
        tpl_after_delete = QueryCall(name="test", arguments=kwargs)
        matches_after = list(test_cache.query(tpl_after_delete))
        assert len(matches_after) >= 1, (
            "Cache.query with arguments=None should still find the call "
            "after deleting keys from the local kwargs dict"
        )
        assert any(m.result == result for m in matches_after)


@given(
    kwargs=kwargs_strategy,
    ignored_val1=st_nested_values,
    ignored_val2=st_nested_values,
)
@settings(max_examples=50, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_ignored_arg_no_default(cache_fixture, kwargs, ignored_val1, ignored_val2):
    """Ignored argument (no default) is excluded from the cache key.

    Verifies that:
      1. ``test.digest`` is identical regardless of the ignored argument's value.
      2. A second call with a different ignored value returns the cached result.
      3. ``Cache.query`` by the non-ignored ``kw`` arguments finds the cached call.
    """
    assume('noise' not in kwargs)
    test_cache = cache_fixture

    @fleche(ignore='noise')
    def test(noise, **kw):
        return kw

    with cache(test_cache):
        # Digest is independent of the ignored argument
        assert test.digest(noise=ignored_val1, **kwargs) == test.digest(noise=ignored_val2, **kwargs)

        result = test(noise=ignored_val1, **kwargs)
        # Different ignored value → same cache entry returned
        result2 = test(noise=ignored_val2, **kwargs)
        assert result == result2

        # 'noise' is stripped from the stored Call; query on the remaining kw args
        tpl = QueryCall(name="test", arguments={'kw': kwargs})
        matches = list(test_cache.query(tpl))
        assert len(matches) >= 1
        assert any(m.result == result for m in matches)


@given(
    kwargs=kwargs_strategy,
    ignored_val=st_nested_values,
)
@settings(max_examples=50, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_ignored_arg_with_default(cache_fixture, kwargs, ignored_val):
    """Ignored argument with default: omitting it or passing any value share the same cache key.

    Verifies that:
      1. Calling without the ignored arg (uses default) produces the same digest as
         calling with an explicit value.
      2. Both calls return the same cached result.
      3. ``Cache.query`` by the non-ignored ``kw`` arguments finds the cached call.
    """
    assume('noise' not in kwargs)
    test_cache = cache_fixture

    @fleche(ignore='noise')
    def test(noise=None, **kw):
        return kw

    with cache(test_cache):
        # Omitting the ignored arg (default) and providing it produce the same digest
        assert test.digest(**kwargs) == test.digest(noise=ignored_val, **kwargs)

        result = test(**kwargs)  # noise defaults to None
        result2 = test(noise=ignored_val, **kwargs)  # explicit ignored value
        assert result == result2

        tpl = QueryCall(name="test", arguments={'kw': kwargs})
        matches = list(test_cache.query(tpl))
        assert len(matches) >= 1
        assert any(m.result == result for m in matches)


@given(
    kwargs=kwargs_strategy,
    required_val=st_nested_values,
)
@settings(max_examples=50, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_required_arg_with_default(cache_fixture, kwargs, required_val):
    """Required argument with default: result cached only when the arg is explicitly provided.

    Verifies that:
      1. Calling without the required arg always executes the function (no caching).
      2. Calling with the required arg caches the result; a subsequent identical call
         is served from cache without re-executing the function.
      3. ``Cache.query`` by the required arg and ``kw`` arguments finds the cached call.
    """
    assume('key' not in kwargs)
    test_cache = cache_fixture

    call_count = [0]

    @fleche(require='key')
    def test(key=None, **kw):
        call_count[0] += 1
        return kw

    with cache(test_cache):
        # Without the required arg → function always executes, result never cached
        test(**kwargs)
        test(**kwargs)
        assert call_count[0] == 2

        # With required arg → cached after first execution (or prior example cache hit)
        result = test(key=required_val, **kwargs)
        count_after_first = call_count[0]
        test(key=required_val, **kwargs)  # always a cache hit from here on
        assert call_count[0] == count_after_first

        tpl = QueryCall(name="test", arguments={'key': required_val, 'kw': kwargs})
        matches = list(test_cache.query(tpl))
        assert len(matches) >= 1
        assert any(m.result == result for m in matches)
