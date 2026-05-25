import builtins
import datetime
import itertools
from dataclasses import dataclass
from typing import Iterable, Iterator, Any, Literal, Callable

import pandas as pd

from . import call


def _resolve_key(key: "str | Callable[[call.LazyCall], Any]") -> "Callable[[call.LazyCall], Any]":
    """Normalise a key argument to a callable.

    When given a string, produce a lookup on ``LazyCall.arguments[key]``.
    """
    if isinstance(key, str):
        arg_name = key
        return lambda c: c.arguments[arg_name]
    return key


@dataclass(frozen=True)
class QueryIterator(Iterable[call.LazyCall]):
    """Re-iterable view over a lazy query result.

    ``calls`` is a zero-argument callable that returns a fresh iterable each
    time it is invoked.  Every ``for`` loop, ``list()``, or consuming method
    therefore starts a new traversal of the underlying source, so the same
    ``QueryIterator`` can be used multiple times and will reflect the current
    state of the cache on each pass.

    Args:
        calls: factory returning an iterable of :class:`~fleche.call.LazyCall`
    """

    calls: Callable[[], Iterable[call.LazyCall]]

    def __iter__(self) -> Iterator[call.LazyCall]:
        yield from self.calls()

    def only(self) -> call.LazyCall:
        """Return the single matching call.

        Raises:
            IndexError: if there are no matching calls
            ValueError: if there is more than one matching call
        """
        it = iter(self)
        try:
            c = builtins.next(it)
        except StopIteration:
            raise IndexError("QueryIterator is empty")
        try:
            builtins.next(it)
            raise ValueError("QueryIterator has more than one result")
        except StopIteration:
            return c

    def count(self) -> int:
        """Return the total number of matching calls."""
        return builtins.sum(1 for _ in self)

    def any(self) -> "call.LazyCall | None":
        """Return the first matching call, or None if there are no matching calls.

        Use `.sorted(reverse=...)` to control which call is returned when ordering matters.
        """
        for c in self:
            return c
        return None

    def empty(self) -> bool:
        """Return True if there are no matching calls."""
        for _ in self:
            return False
        return True

    def take(self, n: int) -> "QueryIterator":
        """Return first n results as a new QueryIterator (lazy)."""
        return QueryIterator(lambda: itertools.islice(iter(self), n))

    def skip(self, n: int) -> "QueryIterator":
        """Skip first n results and return the rest as a new QueryIterator (lazy)."""
        return QueryIterator(lambda: itertools.islice(iter(self), n, None))

    def filter(self, predicate: Callable[[call.LazyCall], bool]) -> "QueryIterator":
        """Return a new QueryIterator keeping only calls where predicate(call) is truthy (lazy)."""
        return QueryIterator(lambda: (c for c in self if predicate(c)))

    def sorted(
        self,
        key: "str | Callable[[call.LazyCall], Any] | None" = None,
        reverse: bool = False,
    ) -> "QueryIterator":
        """Return a new QueryIterator with calls sorted by key.

        Args:
            key: a callable taking a LazyCall, or a string argument name to sort by
            reverse: if True, sort in descending order
        """
        key = _resolve_key(key) if key is not None else None
        return QueryIterator(lambda: builtins.sorted(self, key=key, reverse=reverse))

    def unique(self, key: "str | Callable[[call.LazyCall], Any]") -> "QueryIterator":
        """Return a new QueryIterator with duplicates removed, keeping the first per group (lazy).

        Args:
            key: a callable taking a LazyCall, or a string argument name to deduplicate by
        """
        key = _resolve_key(key)

        def _unique(calls, k):
            seen: set = set()
            for c in calls:
                v = k(c)
                if v not in seen:
                    seen.add(v)
                    yield c

        return QueryIterator(lambda: _unique(self, key))

    def groupby(self, key: "str | Callable[[call.LazyCall], Any]") -> "dict[Any, QueryIterator]":
        """Partition calls into a dict of QueryIterators keyed by group value.

        Args:
            key: a callable taking a LazyCall, or a string argument name to group by
        """
        key = _resolve_key(key)
        groups: dict[Any, list] = {}
        for c in self:
            k = key(c)
            if k not in groups:
                groups[k] = []
            groups[k].append(c)
        return {k: QueryIterator(lambda v=v: v) for k, v in groups.items()}

    def _timestop_extremum(self, *, reverse: bool) -> call.LazyCall:
        sentinel = float("-inf") if reverse else float("inf")
        result = (builtins.max if reverse else builtins.min)(
            self,
            key=lambda c: c.metadata.get("runtime", {}).get("timestop", sentinel),
            default=None,
        )
        if result is None:
            raise IndexError("QueryIterator is empty")
        return result

    def latest(self) -> call.LazyCall:
        """Return the call with the most recent timestop (requires Runtime metadata).

        Raises:
            IndexError: if there are no matching calls
        """
        return self._timestop_extremum(reverse=True)

    def oldest(self) -> call.LazyCall:
        """Return the call with the oldest timestop (requires Runtime metadata).

        Raises:
            IndexError: if there are no matching calls
        """
        return self._timestop_extremum(reverse=False)

    def evict(self) -> None:
        """Remove all matched calls from the cache."""
        for c in self:
            c._cache.evict(c.to_lookup_key())

    def transfer(self, target, pop: bool = False, overwrite: bool = False) -> None:
        """Replay matching calls into the target cache.

        Args:
            target: destination :class:`~fleche.caches.BaseCache`.
            pop: if True, evict transferred calls from the source cache.
            overwrite: if True, overwrite entries already present in the target.
                If False (default), conflicts are skipped.
        """
        for c in self:
            key = c.to_lookup_key()
            conflict = not overwrite and target.contains(key)
            if not conflict:
                target.save(c.fetch())
            if pop and not conflict:
                c._cache.evict(key)

    def table(self, arguments: Iterable[str] | str | Literal[True] = (), results=False) -> pd.DataFrame:
        """Return a pandas DataFrame summarizing queried calls.

        Arguments and results are elided.

        The DataFrame index will be the lookup key (digest) of each call.
        Columns are:
            - `name`: the function name
            - `module`: the module name
            - 'result`: if `results` argument is `True`
            - metadata fields are flattened and added as columns directly

        If given argument names collide with any of the above columns, the are prefixed by 'a_'.
        Only requested arguments are loaded from cache.

        ``timestart`` and ``timestop`` columns (produced by the :class:`~fleche.metadata.Runtime`
        metadata) are automatically converted from UTC Unix timestamps (float seconds) to
        timezone-aware :class:`pandas.Timestamp` objects in the local timezone.

        Args:
            arguments: add the given arguments (of the queried calls) as columns to the table.
                Pass ``True`` to add all arguments, or a single string as a shortcut for a
                one-element tuple.
            results (bool): if True, add results of queried calls to table

        Returns:
            :class:`pandas.DataFrame`: table of all calls on cache
        """

        if arguments is True:
            pass
        elif isinstance(arguments, str):
            arguments = (arguments,)
        else:
            arguments = tuple(arguments)

        rows: dict[str, dict[str, Any]] = {}
        for c in self:
            row = {
                    prop: getattr(c, prop) for prop in ("name", "module", "metadata")
            }
            if results:
                row["result"] = c.result
            md = row.pop("metadata", {}) or {}
            # Flatten each metadata name's dict into the row first, so argument
            # clash detection below also catches metadata-produced keys.
            for data in md.values():
                if isinstance(data, dict):
                    row.update(data)
            for a in (c.arguments.keys() if arguments is True else arguments):
                # TODO: quick and easy strategy to avoid name clashes, alternative would be to use multicolumns, but
                # those are a bit annoying
                if a not in row:
                    row[a] = c.arguments.get(a, None)
                else:
                    row[f"a_{a}"] = c.arguments.get(a, None)
            rows[str(c.to_lookup_key())] = row

        df = pd.DataFrame.from_dict(rows, orient="index")
        local_tz = datetime.datetime.now(datetime.timezone.utc).astimezone().tzinfo
        for col in ("timestart", "timestop"):
            if col in df.columns:
                df[col] = pd.to_datetime(df[col], unit="s", utc=True).dt.tz_convert(local_tz)
        return df

    def results(self) -> Iterator[Any]:
        """Returns an iterator over the results of queried calls."""
        for c in self:
            yield c.result
