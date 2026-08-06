"""Two-phase save protocol: Cache.prepare / PreparedCall.commit / abandon.

The protocol exists to fix one incoherence: the wrapper digests arguments
*before* the function body runs (the lookup key), but the old save path
re-digested them from their live values *after* — so a function that mutated
an argument was recorded under post-mutation content and could never be found
by an honest repeat call.  Under the two-phase protocol the recorded identity
is sealed at prepare time.
"""
import pytest

from fleche import fleche
import fleche as fl
from fleche.call import Call
from fleche.caches import Cache, CacheStack, RefreshingCache, Rejected
from fleche.digest import digest
from fleche.storage.memory import ValueMemory, CallMemory


@pytest.fixture
def cache():
    return Cache(ValueMemory({}), CallMemory({}))


def make_call(**arguments):
    return Call(name="f", arguments=arguments, module="m", version="1")


# ---- PreparedCall lifecycle ----


def test_prepare_seals_lookup_key(cache):
    call = make_call(x=1, y="a")
    prepared = cache.prepare(call)
    assert prepared.digested.to_lookup_key() == call.to_lookup_key()


def test_prepare_stores_arguments_before_commit(cache):
    call = make_call(x=[1, 2])
    cache.prepare(call)
    assert cache.values.load(digest([1, 2])) == [1, 2]


def test_commit_files_record_under_sealed_key(cache):
    call = make_call(x=1)
    prepared = cache.prepare(call)
    key = prepared.commit("result", {"meta": {"k": "v"}})
    assert key == call.to_lookup_key()
    loaded = cache.load(key)
    assert loaded.result == "result"
    assert loaded.metadata == {"meta": {"k": "v"}}


def test_commit_captures_result_at_commit_time(cache):
    """A mutated argument passed back out is stored in its *final* state."""
    xs = [1, 2]
    call = make_call(x=xs)
    prepared = cache.prepare(call)
    xs.append(3)                     # the "function body" mutates the argument
    key = prepared.commit(xs)
    loaded = cache.load(key)
    assert loaded.result == [1, 2, 3]           # result: final state
    assert loaded.arguments["x"] == [1, 2]      # argument: initial state


def test_abandon_leaves_no_record(cache):
    call = make_call(x=1)
    prepared = cache.prepare(call)
    prepared.abandon()
    assert not cache.contains(call.to_lookup_key())


def test_context_manager_abandons_without_commit(cache):
    call = make_call(x=1)
    with cache.prepare(call) as prepared:
        pass
    assert not cache.contains(call.to_lookup_key())


def test_context_manager_commit_sticks(cache):
    call = make_call(x=1)
    with cache.prepare(call) as prepared:
        prepared.commit(42)
    assert cache.load(call.to_lookup_key()).result == 42


def test_context_manager_does_not_swallow_exceptions(cache):
    call = make_call(x=1)
    with pytest.raises(RuntimeError):
        with cache.prepare(call):
            raise RuntimeError("body failed")
    assert not cache.contains(call.to_lookup_key())


def test_commit_is_exactly_once(cache):
    prepared = cache.prepare(make_call(x=1))
    prepared.commit(1)
    with pytest.raises(RuntimeError):
        prepared.commit(2)


def test_abandon_is_idempotent_but_bars_commit(cache):
    prepared = cache.prepare(make_call(x=1))
    prepared.abandon()
    prepared.abandon()
    with pytest.raises(RuntimeError):
        prepared.commit(1)


def test_commit_does_not_mutate_the_prepared_record(cache):
    prepared = cache.prepare(make_call(x=1))
    prepared.commit("r")
    assert prepared.digested.result is None


def test_readonly_prepare_is_digest_only_and_commit_rejects(cache):
    """A read-only cache admits the call without writing anything; the
    rejection lands at commit time, after the body would have run."""
    call = make_call(x=[1, 2])
    prepared = cache.readonly().prepare(call)
    assert prepared.digested.to_lookup_key() == call.to_lookup_key()
    assert list(cache.values.list()) == []          # nothing was stashed
    with pytest.raises(Rejected):
        prepared.commit(42)
    assert not cache.contains(call.to_lookup_key())


def test_key_matches_one_shot_save(cache):
    """prepare/commit and the legacy one-shot save file under the same key."""
    call = make_call(x={"a": 1})
    call.result = "r"
    one_shot = Cache(ValueMemory({}), CallMemory({}))
    assert cache.prepare(call).commit("r") == one_shot.save(call)


# ---- wrappers and stacks: storage from the inner cache, policy from the outer ----


def test_stack_prepares_on_stack0_and_commits_through_the_stack(cache):
    """Arguments are stashed where the stack's saves land; the commit still
    goes through the stack itself (its ``save`` policy, not stack[0]'s)."""
    second = Cache(ValueMemory({}), CallMemory({}))
    stack = CacheStack([cache, second])
    call = make_call(x=[1, 2])
    prepared = stack.prepare(call)
    assert prepared.cache is stack
    key = prepared.commit([1, 2, 3])
    assert key == call.to_lookup_key()
    assert cache.load(key).result == [1, 2, 3]
    assert cache.load(key).arguments["x"] == [1, 2]
    assert not second.contains(key)


def test_wrapper_prepare_commits_through_the_wrapper(cache):
    """A wrapper delegates storage to its inner cache but keeps its own save
    policy on the commit — here the refresh wrapper's write-through."""
    wrapper = RefreshingCache(cache)
    call = make_call(x=[1, 2])
    prepared = wrapper.prepare(call)
    assert prepared.cache is wrapper
    key = prepared.commit("r")
    assert cache.load(key).result == "r"
    assert cache.load(key).arguments["x"] == [1, 2]


# ---- end-to-end: argument mutation no longer corrupts identity ----


def test_mutating_consumer_hits_on_honest_repeat(cache):
    """A function that mutates its argument is keyed on the *pre-call* state:
    a repeat call with the same initial state is a hit."""
    runs = []

    @fleche
    def consume(xs: list):
        runs.append(1)
        xs.append(99)
        return sum(xs)

    with fl.cache(cache):
        assert consume([1, 2]) == 102
        assert consume([1, 2]) == 102
    assert len(runs) == 1


def test_no_mislabeled_entry_for_mutated_state(cache):
    """The post-mutation argument state is a *different* call and recomputes —
    the old behavior filed the first call under this state (a false hit that
    returned a result computed from different input)."""
    runs = []

    @fleche
    def consume(xs: list):
        runs.append(1)
        xs.append(99)
        return len(xs)

    with fl.cache(cache):
        assert consume([1, 2]) == 3
        assert consume([1, 2, 99]) == 4  # miss: its own honest computation
    assert len(runs) == 2


@pytest.mark.parametrize("exc", [Rejected("no admission"), OSError("storage down")])
def test_prepare_failure_degrades_to_uncached(exc):
    """A prepare that fails — policy rejection or actual error — must not stop
    the call: the body runs and the result comes back uncached."""

    class Broken(Cache):
        def prepare(self, call):
            raise exc

    broken = Broken(ValueMemory({}), CallMemory({}))
    runs = []

    @fleche
    def f(x):
        runs.append(1)
        return x + 1

    with fl.cache(broken):
        assert f(1) == 2
        assert f(1) == 2
    assert len(runs) == 2  # never cached: prepare fails on every call
    assert list(broken.calls.list()) == []


def test_body_exception_leaves_no_record(cache):
    runs = []

    @fleche
    def boom(x):
        runs.append(1)
        raise ValueError("no")

    with fl.cache(cache):
        for _ in range(2):
            with pytest.raises(ValueError):
                boom(1)
        assert len(runs) == 2            # nothing cached, body ran twice
        assert not boom.contains(1)
