from dataclasses import dataclass
from typing import Iterable

from . import call


@dataclass(frozen=True)
class QueryIterator:
    calls: Iterable[call.LazyCall]

    def __iter__(self) -> Iterable[call.LazyCall]:
        yield from self.calls
