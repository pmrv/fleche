import builtins
import datetime
import itertools
import logging
from dataclasses import dataclass, field
from typing import Iterable, Iterator, Any, Literal, Callable, TYPE_CHECKING

import pandas as pd

from . import call

if TYPE_CHECKING:
    from .caches import BaseCache

logger = logging.getLogger("fleche.query")


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
        cache: the cache that produced these calls; set by
            :meth:`~fleche.caches.BaseCache.query` and propagated through
            chainable methods.  Used by :meth:`table` to call ``shrink``
            without reaching into ``LazyCall._cache``.
    """

    calls: Callable[[], Iterable[call.LazyCall]]
    cache: "BaseCache | None" = field(default=None, repr=False)

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
        return QueryIterator(lambda: itertools.islice(iter(self), n), cache=self.cache)

    def skip(self, n: int) -> "QueryIterator":
        """Skip first n results and return the rest as a new QueryIterator (lazy)."""
        return QueryIterator(lambda: itertools.islice(iter(self), n, None), cache=self.cache)

    def filter(self, predicate: Callable[[call.LazyCall], bool]) -> "QueryIterator":
        """Return a new QueryIterator keeping only calls where predicate(call) is truthy (lazy)."""
        return QueryIterator(lambda: (c for c in self if predicate(c)), cache=self.cache)

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
        return QueryIterator(lambda: builtins.sorted(self, key=key, reverse=reverse), cache=self.cache)

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

        return QueryIterator(lambda: _unique(self, key), cache=self.cache)

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
        return {k: QueryIterator(lambda v=v: v, cache=self.cache) for k, v in groups.items()}

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
            if conflict:
                logger.warning(
                    "Not transferring %s: already exists in target and overwrite=False",
                    target.shrink(key),
                )
                continue
            target.save(c.fetch())
            if pop:
                c._cache.evict(key)

    def table(
        self,
        arguments: Iterable[str] | str | Literal[True] = (),
        results=False,
        shrink_keys: bool = True,
    ) -> pd.DataFrame:
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
            shrink_keys (bool): if True (default), shrink each lookup key in the
                index to its shortest unambiguous prefix via the owning cache's
                ``shrink``.  Falls back to the full digest if shrinking raises
                :class:`~fleche.storage.base.AmbiguousDigestError`.  Set to
                ``False`` to keep full-length digests (cheaper on large caches).

        Returns:
            :class:`pandas.DataFrame`: table of all calls on cache
        """

        if arguments is True:
            pass
        elif isinstance(arguments, str):
            arguments = (arguments,)
        else:
            arguments = tuple(arguments)

        items = list(self)
        keys = [c.to_lookup_key() for c in items]
        if shrink_keys and items:
            # Full 64-char digests are unambiguous modulo SHA-256 collision,
            # so we let AmbiguousDigestError propagate rather than silently
            # falling back — a hit here means our hash assumptions are broken.
            shrink_cache = self.cache or items[0]._cache
            shrunk = shrink_cache.shrink(*keys)
            if len(keys) == 1:
                shrunk = (shrunk,)
            keys = list(shrunk)

        rows: dict[str, dict[str, Any]] = {}
        for c, key in zip(items, keys):
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
            rows[str(key)] = row

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
