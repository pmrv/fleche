import datetime
from dataclasses import dataclass
from typing import Iterable, Iterator, Any

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

    def table(self, arguments: Iterable[str] | str | bool = (), results=False) -> pd.DataFrame:
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

        if isinstance(arguments, str):
            arguments = (arguments,)
        elif arguments is not True:
            arguments = tuple(arguments)

        rows: dict[str, dict[str, Any]] = {}
        for c in self.calls:
            row = {
                    prop: getattr(c, prop) for prop in ("name", "module", "metadata")
            }
            if results:
                row["result"] = c.result
            for a in (c.arguments.keys() if arguments is True else arguments):
                # TODO: quick and easy strategy to avoid name clashes, alternative would be to use multicolumns, but
                # those are a bit annoying
                if a not in row:
                    row[a] = c.arguments.get(a, None)
                else:
                    row[f"a_{a}"] = c.arguments.get(a, None)
            md = row.pop("metadata", {}) or {}
            # Flatten each metadata name's dict into the row
            for data in md.values():
                if isinstance(data, dict):
                    row.update(data)
            rows[str(c.to_lookup_key())] = row

        df = pd.DataFrame.from_dict(rows, orient="index")
        local_tz = datetime.datetime.now(datetime.timezone.utc).astimezone().tzinfo
        for col in ("timestart", "timestop"):
            if col in df.columns:
                df[col] = pd.to_datetime(df[col], unit="s", utc=True).dt.tz_convert(local_tz)
        return df

    def results(self) -> Iterable[Any]:
        """Returns an iterable over the results of queried calls."""
        for c in self.calls:
            yield c.result
