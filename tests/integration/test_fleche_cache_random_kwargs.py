"""Integration test: random kwargs through @fleche, then query via Cache.query and function.query."""

import random
import string

import hypothesis.strategies as st
from hypothesis import given, settings

from fleche import fleche, cache
from fleche.call import QueryCall
from fleche.caches import Cache
from fleche.storage import Memory

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
@settings(max_examples=100, deadline=None)
def test_fleche_cache_query_random_kwargs(kwargs):
    """Cache.query and function.query(**kwargs) yield back a cached call.

    After calling the decorated function, verify that:
      1. ``function.query(**kwargs)`` returns the call (exact match).
      2. ``Cache.query`` with a name-only (wildcard) template returns the call.
      3. After deleting random keys from the kwargs, a wildcard query on
         ``Cache.query`` still yields the original call.
    """

    test_cache = Cache(values=Memory({}), _calls=Memory({}))

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

        # --- 2. Cache.query with wildcard arguments ------------------------
        tpl = QueryCall(name="test", arguments={"kwargs": None})
        cache_matches = list(test_cache.query(tpl))
        assert len(cache_matches) >= 1, (
            "Cache.query with wildcarded kwargs should find the call"
        )
        # --- 3. Delete random keys, then query ----------------------------
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
