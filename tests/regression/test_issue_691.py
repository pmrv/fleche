"""Regression test for issue #691.

https://github.com/pmrv/fleche/issues/691

A plain (non-fleche) function that merely *calls* a fleche-decorated
function did not get cache hits when submitted via a wrap_executor'd
ProcessPoolExecutor: only the outer callable was inspected by ``submit``,
and since it had no ``.fleche`` namespace it was forwarded to the executor
unbound, so the worker process never saw the active cache. ``submit`` now
always applies ``BoundWrapper.bind`` to non-fleche callables too, so the
active cache/metadata state is carried into the worker regardless of which
function in the call chain is actually decorated.
"""

import concurrent.futures
import pathlib

import fleche


def _issue_691_slow(t, marker_path):
    """Analogue of ``slow`` from the issue; records every real invocation."""
    path = pathlib.Path(marker_path)
    path.write_text(str(int(path.read_text()) + 1))
    return t


_issue_691_slow = fleche.fleche(_issue_691_slow)


def _issue_691_carries_slow(t, marker_path):
    """Analogue of ``carries_slow``: plain function, not itself fleche-decorated."""
    return _issue_691_slow(t, marker_path)


def test_wrap_executor_binds_plain_wrapper_around_fleche_call(file_cache, tmp_path):
    """A plain wrapper around a fleche call gets cache hits across processes.

    Uses ``max_tasks_per_child=1`` so each submission spawns a fresh worker
    process with no warm in-memory state, matching the reproduction steps
    from the issue.
    """
    marker = tmp_path / "marker"
    marker.write_text("0")

    with fleche.cache(file_cache):
        with concurrent.futures.ProcessPoolExecutor(
            max_workers=1, max_tasks_per_child=1
        ) as executor:
            fleche.wrap_executor(executor)
            first = executor.submit(
                _issue_691_carries_slow, 3, str(marker)
            ).result()

    with fleche.cache(file_cache):
        with concurrent.futures.ProcessPoolExecutor(
            max_workers=1, max_tasks_per_child=1
        ) as executor:
            fleche.wrap_executor(executor)
            second = executor.submit(
                _issue_691_carries_slow, 3, str(marker)
            ).result()

    assert first == 3
    assert second == 3
    assert file_cache.contains(_issue_691_slow.digest(3, str(marker)))
    # The inner fleche-decorated call must only have actually executed once:
    # the second pass is served from cache even though ``carries_slow`` itself
    # is a plain, non-fleche function.
    assert marker.read_text() == "1", (
        "carries_slow is not itself fleche-decorated, but wrap_executor must "
        "still bind the active cache into the worker so the nested call to "
        "the fleche-decorated `slow` gets a cache hit on the second pass."
    )
