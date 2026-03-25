"""Integration test: random kwargs through @fleche, then query via Cache.query and function.query."""

import random
from dataclasses import dataclass

import hypothesis.strategies as st
from hypothesis import given, settings

from fleche import fleche, cache
from fleche.call import QueryCall
from fleche.caches import Cache
from fleche.storage import Memory


# ---------------------------------------------------------------------------
# Sample dataclasses for hypothesis
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Point:
    x: float
    y: float


@dataclass(frozen=True)
class Config:
    name: str
    value: int


# ---------------------------------------------------------------------------
# Hypothesis strategy for values that fleche can digest
# ---------------------------------------------------------------------------

_leaf = st.one_of(
    st.integers(),
    st.floats(allow_nan=False, allow_infinity=False),
    st.text(max_size=20),
    st.booleans(),
    st.none(),
    st.binary(max_size=20),
    st.builds(Point, x=st.floats(allow_nan=False, allow_infinity=False),
                      y=st.floats(allow_nan=False, allow_infinity=False)),
    st.builds(Config, name=st.text(max_size=10), value=st.integers()),
)

digestable_values = st.recursive(
    _leaf,
    lambda children: st.one_of(
        st.lists(children, max_size=3),
        st.tuples(children, children),
        st.dictionaries(st.text(max_size=10), children, max_size=3),
    ),
    max_leaves=5,
)

# Strategy for valid Python-identifier keys mapped to digestable values
_ident_chars = "abcdefghijklmnopqrstuvwxyz"
_ident_key = st.text(alphabet=_ident_chars, min_size=1, max_size=8)

kwargs_strategy = st.dictionaries(
    _ident_key.filter(lambda k: k != "metadata"),  # 'metadata' is reserved by .query()
    digestable_values,
    min_size=1,
    max_size=6,
)


# ---------------------------------------------------------------------------
# Test
# ---------------------------------------------------------------------------

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
        assert any(m.result == result for m in cache_matches)

        # --- 3. Delete random keys, then query ----------------------------
        keys = list(kwargs.keys())
        n_delete = random.randint(1, len(keys))
        for k in random.sample(keys, n_delete):
            del kwargs[k]

        # The stored call is untouched; a fully wildcarded query must
        # still return it.
        tpl_after_delete = QueryCall(name="test", arguments=None)
        matches_after = list(test_cache.query(tpl_after_delete))
        assert len(matches_after) >= 1, (
            "Cache.query with arguments=None should still find the call "
            "after deleting keys from the local kwargs dict"
        )
        assert any(m.result == result for m in matches_after)

        # If any keys remain, an exact query on the remaining subset
        # should NOT accidentally match (the digest changed).
        if kwargs:
            subset_matches = list(test.query(**kwargs))
            assert not any(m.result == result for m in subset_matches), (
                "Querying with a strict subset of kwargs must not match "
                "the original call (different digest)"
            )
