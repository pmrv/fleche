import pytest

from fleche import fleche, cache, tags


def test_wrapper_query_integration(cache_fixture):
    """Integration: run functions, then query via wrapper.query with metadata.

    Intent: Ensure that the end-to-end flow of saving calls/results through the
    decorator and retrieving matching calls through the wrapper's query method
    (which leverages Cache.query) works. Verifies:
      - Arguments are normalized and saved
      - Metadata is captured via tags()
      - wrapper.query() returns calls with decoded arguments/results
      - Metadata filters in the template produce the expected subset
    """

    test_cache = cache_fixture

    @fleche
    def add(a, b):
        return a + b

    @fleche
    def noise(a, b):
        return b - a

    # Use our test cache for this block
    with cache(test_cache):
        # Run calls under different tags
        with tags(project="alpha", phase="train"):
            add(1, 2)
            add(a=3, b=4)
            noise(
                1, 2
            )  # insert different function with same args into the cache to ensure name check works
        with tags(project="beta", phase="eval"):
            add(10, 4)
            noise(10, 4)

        calls_alpha = list(
            add.query(a=None, b=None, metadata={"tags": {"project": "alpha"}})
        )
        assert (
            len(calls_alpha) >= 1
        ), "Expected at least one 'alpha' tagged call found via wrapper.query"
        for c in calls_alpha:
            assert (
                c.name == "add"
            ), "Query by function wrapper should return calls of that function"
            assert (
                c.metadata.get("tags", {}).get("project") == "alpha"
            ), "Metadata filter should be enforced"
            # Ensure results and args are decoded
            assert isinstance(
                c.arguments.get("a"), (int, float)
            ), "Argument 'a' should be decoded from value store"
            assert isinstance(
                c.result, (int, float)
            ), "Result should be decoded from value store"

        calls_train = add.query(a=None, b=None, metadata={"tags": {"project": "beta"}})
        assert any(
            c.arguments.get("a") == 10 and c.arguments.get("b") == 4
            for c in calls_train
        ), "Should retrieve the (3,4) call when filtering by tags.phase == 'eval'"

        calls_4 = add.query(a=None, b=4)
        for c in calls_4:
            assert (
                c.name == "add"
            ), "Query by function wrapper should return calls of that function"
            assert (
                c.arguments.get("b") == 4
            ), "Query should only return calls where arguments match"


def test_query_by_result_integration(cache_fixture):
    """Integration: query by result value using a Call template via cache().query.

    Intent: Ensure we can filter by the result of a call using digest semantics.
    We use the same Sql calls store and Memory values store to demonstrate that
    querying by result returns the expected call(s).
    """
    from fleche.call import Call

    test_cache = cache_fixture

    @fleche
    def add(a, b):
        return a + b

    with cache(test_cache):
        # Populate
        add(1, 2)  # result 3
        add(10, 4)  # result 14

        # Build a template filtering by result only; name ensures function match
        tpl = Call(
            name="add",
            arguments=None,
            metadata=None,
            module=None,
            version=None,
            result=14,
        )
        matches = list(cache().query(tpl))
        assert any(
            c.result == 14 for c in matches
        ), "At least one returned call must have result 14"
        # Verify all returned calls are from the right function and correct result
        for c in matches:
            assert c.name == "add", "Result filter should match the correct function"
            assert c.result == 14, "All matched calls must have the requested result"
