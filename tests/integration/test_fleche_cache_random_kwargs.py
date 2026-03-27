"""Integration test: random kwargs through @fleche, then query via Cache.query and function.query."""

import keyword
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


def _exec_fn(params_str, body_lines, extra_globals=None):
    """Execute a function definition and return it.

    Using explicit keyword params (instead of **kw) means stored call.arguments
    is a flat dict, so QueryCall(arguments=subset_dict) works directly.
    """
    src = f"def test({params_str}):\n" + "\n".join(f"    {line}" for line in body_lines)
    ns = dict(extra_globals or {})
    exec(src, ns)
    return ns["test"]


def _kwparams(names, default=None):
    """Build a parameter string for exec: 'a, b, c' or 'a=None, b=None, c=None'."""
    if default is None:
        return ", ".join(names)
    return ", ".join(f"{n}={default}" for n in names)


def _retdict(names):
    """Build a dict-literal return expression for exec: {'a': a, 'b': b}."""
    return "{" + ", ".join(f"{repr(k)}: {k}" for k in names) + "}"


@given(kwargs=kwargs_strategy)
@settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_fleche_cache_query_random_kwargs(cache_fixture, kwargs):
    """Cache.query and function.query(**kwargs) yield back a cached call.

    After calling the decorated function, verify that:
      1. ``function.query(**kwargs)`` returns the call (exact match).
      2. After deleting random keys from the local kwargs dict, a subset
         ``Cache.query`` still yields the original call.
    """
    assume(not any(keyword.iskeyword(k) for k in kwargs))

    test_cache = cache_fixture
    kw_names = list(kwargs.keys())

    # Explicit params → stored arguments == kwargs (flat dict, not nested under **kw)
    test = fleche(_exec_fn(_kwparams(kw_names), [f"return {_retdict(kw_names)}"]))

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

        # The stored call is untouched; a subset-argument query must
        # still return it.
        tpl_after_delete = QueryCall(name="test", arguments=kwargs)
        matches_after = list(test_cache.query(tpl_after_delete))
        assert len(matches_after) >= 1, (
            "Cache.query with a subset of the original kwargs should still find "
            "the call after deleting keys from the local dict"
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
      2. The cache contains an entry for calls with a different ignored value.
      3. ``Cache.query`` by the non-ignored kwargs finds the cached call.
    """
    assume('noise' not in kwargs)
    assume(not any(keyword.iskeyword(k) for k in kwargs))
    test_cache = cache_fixture
    kw_names = list(kwargs.keys())

    # 'noise' is an explicit named param so fleche(ignore='noise') can strip it;
    # remaining params are explicit → stored arguments == kwargs (flat)
    test_fn = fleche(ignore='noise')(
        _exec_fn(f"noise, {_kwparams(kw_names)}", [f"return {_retdict(kw_names)}"])
    )

    with cache(test_cache):
        # Digest is independent of the ignored argument
        assert test_fn.digest(noise=ignored_val1, **kwargs) == test_fn.digest(noise=ignored_val2, **kwargs)

        result = test_fn(noise=ignored_val1, **kwargs)
        # Different ignored value → same cache entry
        assert test_fn.contains(noise=ignored_val2, **kwargs)

        # 'noise' is stripped from the stored Call; remaining kwargs are stored flat
        tpl = QueryCall(name="test", arguments=kwargs)
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
      2. The cache contains an entry for calls with an explicit ignored value.
      3. ``Cache.query`` by the non-ignored kwargs finds the cached call.
    """
    assume('noise' not in kwargs)
    assume(not any(keyword.iskeyword(k) for k in kwargs))
    test_cache = cache_fixture
    kw_names = list(kwargs.keys())

    test_fn = fleche(ignore='noise')(
        _exec_fn(
            f"noise=None, {_kwparams(kw_names, default='None')}",
            [f"return {_retdict(kw_names)}"],
        )
    )

    with cache(test_cache):
        # Omitting the ignored arg (default) and providing it produce the same digest
        assert test_fn.digest(**kwargs) == test_fn.digest(noise=ignored_val, **kwargs)

        result = test_fn(**kwargs)  # noise defaults to None
        # Calling with an explicit ignored value hits the same cache entry
        assert test_fn.contains(noise=ignored_val, **kwargs)

        tpl = QueryCall(name="test", arguments=kwargs)
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
      3. ``Cache.query`` by the required arg and remaining kwargs finds the cached call.
    """
    assume('key' not in kwargs)
    assume(not any(keyword.iskeyword(k) for k in kwargs))
    test_cache = cache_fixture
    kw_names = list(kwargs.keys())

    call_count = [0]

    # Build the function with call_count in scope so we can track executions
    test_fn = fleche(require='key')(
        _exec_fn(
            f"key=None, {_kwparams(kw_names, default='None')}",
            ["call_count[0] += 1", f"return {_retdict(kw_names)}"],
            extra_globals={"call_count": call_count},
        )
    )

    with cache(test_cache):
        # Without the required arg → function always executes, result never cached
        test_fn(**kwargs)
        test_fn(**kwargs)
        assert call_count[0] == 2

        # With required arg → cached after first execution (or prior example cache hit)
        result = test_fn(key=required_val, **kwargs)
        count_after_first = call_count[0]
        test_fn(key=required_val, **kwargs)  # always a cache hit from here on
        assert call_count[0] == count_after_first

        tpl = QueryCall(name="test", arguments={**kwargs, 'key': required_val})
        matches = list(test_cache.query(tpl))
        assert len(matches) >= 1
        assert any(m.result == result for m in matches)
