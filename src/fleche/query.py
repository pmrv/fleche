import builtins
import datetime
import itertools
from dataclasses import dataclass
from typing import Iterable, Iterator, Any, Literal, Callable

import pandas as pd

from . import call


@dataclass(frozen=True)
class QueryIterator(Iterable[call.LazyCall]):
    """Iterator that adds some convenience to plain iterators over calls of query result.

    Args:
        calls: (iterable of call.LazyCall): underlying results of the query"""

    calls: Iterable[call.LazyCall]

    def __iter__(self) -> Iterator[call.LazyCall]:
        yield from self.calls

    def first(self) -> call.LazyCall:
        """Return the first matching call.

        Raises:
            IndexError: if there are no matching calls
        """
        for c in self:
            return c
        raise IndexError("QueryIterator is empty")

    def last(self) -> call.LazyCall:
        """Return the last matching call.

        Raises:
            IndexError: if there are no matching calls
        """
        result = None
        found = False
        for c in self:
            result = c
            found = True
        if not found:
            raise IndexError("QueryIterator is empty")
        return result  # type: ignore[return-value]

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

    def any(self) -> bool:
        """Return True if at least one matching call exists (short-circuits)."""
        for _ in self:
            return True
        return False

    def empty(self) -> bool:
        """Return True if there are no matching calls."""
        return not self.any()

    def take(self, n: int) -> "QueryIterator":
        """Return first n results as a new QueryIterator (lazy)."""
        return QueryIterator(itertools.islice(iter(self), n))

    def skip(self, n: int) -> "QueryIterator":
        """Skip first n results and return the rest as a new QueryIterator (lazy)."""
        return QueryIterator(itertools.islice(iter(self), n, None))

    def filter(self, predicate: Callable[[call.LazyCall], bool]) -> "QueryIterator":
        """Return a new QueryIterator keeping only calls where predicate(call) is truthy (lazy)."""
        return QueryIterator(c for c in self.calls if predicate(c))

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
        if isinstance(key, str):
            arg_name = key
            key = lambda c: c.arguments[arg_name]
        return QueryIterator(builtins.sorted(self, key=key, reverse=reverse))

    def unique(self, key: "str | Callable[[call.LazyCall], Any]") -> "QueryIterator":
        """Return a new QueryIterator with duplicates removed, keeping the first per group (lazy).

        Args:
            key: a callable taking a LazyCall, or a string argument name to deduplicate by
        """
        if isinstance(key, str):
            arg_name = key
            key = lambda c: c.arguments[arg_name]

        def _unique(calls, k):
            seen: set = set()
            for c in calls:
                v = k(c)
                if v not in seen:
                    seen.add(v)
                    yield c

        return QueryIterator(_unique(self.calls, key))

    def groupby(self, key: "str | Callable[[call.LazyCall], Any]") -> "dict[Any, QueryIterator]":
        """Partition calls into a dict of QueryIterators keyed by group value.

        Args:
            key: a callable taking a LazyCall, or a string argument name to group by
        """
        if isinstance(key, str):
            arg_name = key
            key = lambda c: c.arguments[arg_name]
        groups: dict[Any, list] = {}
        for c in self:
            k = key(c)
            if k not in groups:
                groups[k] = []
            groups[k].append(c)
        return {k: QueryIterator(v) for k, v in groups.items()}

    def latest(self) -> call.LazyCall:
        """Return the call with the most recent timestart (requires Runtime metadata).

        Raises:
            IndexError: if there are no matching calls
        """
        calls = builtins.list(self)
        if not calls:
            raise IndexError("QueryIterator is empty")
        return builtins.max(calls, key=lambda c: c.metadata.get("runtime", {}).get("timestart", float("-inf")))

    def oldest(self) -> call.LazyCall:
        """Return the call with the oldest timestart (requires Runtime metadata).

        Raises:
            IndexError: if there are no matching calls
        """
        calls = builtins.list(self)
        if not calls:
            raise IndexError("QueryIterator is empty")
        return builtins.min(calls, key=lambda c: c.metadata.get("runtime", {}).get("timestart", float("inf")))

    def evict(self) -> None:
        """Remove all matched calls from the cache."""
        for c in self:
            c._cache.evict(c.to_lookup_key())

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
        for c in self.calls:
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
        for c in self.calls:
            yield c.result
