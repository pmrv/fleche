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

    def table(self) -> pd.DataFrame:
        """Return a pandas DataFrame summarizing queried calls.

        Arguments and results are elided.

        The DataFrame index will be the lookup key (digest) of each call.

        Returns:
            :class:`pandas.DataFrame`: table of all calls on cache
        """

        rows: dict[str, dict[str, Any]] = {}
        for c in self.calls:
            row = {
                    prop: getattr(c, prop) for prop in ("name", "module", "metadata")
            }
            md = row.pop("metadata", {}) or {}
            # Flatten each metadata name's dict into the row
            for data in md.values():
                if isinstance(data, dict):
                    row.update(data)
            rows[str(c.to_lookup_key())] = row

        return pd.DataFrame.from_dict(rows, orient="index")

    def results(self) -> Iterable[Any]:
        """Returns an iterable over the results of queried calls."""
        for c in self.calls:
            yield c.result
