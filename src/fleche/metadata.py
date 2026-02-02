from abc import ABC, abstractmethod
from dataclasses import dataclass
import time
from typing import Any

import pandas as pd

from .digest import digest


class MetaDB(ABC):
    """Interface for databases that keep metadata."""
    @abstractmethod
    def save(self, digest, metadata: dict[str, dict[str, Any]]):
        """Save a given metadata entry."""
        ...

    @abstractmethod
    def load(self, digest) -> dict[str, dict[str, Any]]:
        """Load a given metadata entry."""
        ...

    @abstractmethod
    def table(self, **kwargs) -> pd.DataFrame:
        """Return a display-friendly table of all metadata entries.

        Entries can be filtered using the kwargs."""
        ...


@dataclass
class PandasDB(MetaDB):
    tables: dict[str, pd.DataFrame]

    def save(self, digest, metadata):
        for name, data in metadata.items():
            df = pd.DataFrame([data], index=[digest])
            if name in self.tables:
                self.tables[name] = pd.concat([self.tables[name], df])
            else:
                self.tables[name] = df

    def load(self, digest) -> dict[str, dict[str, Any]]:
        return {m: t.loc[digest] for m, t in self.tables.items() if digest in t.index}

    def table(self, **kwargs) -> pd.DataFrame:
        # join all tables on index
        df = pd.concat(self.tables.values(), axis=1)
        if kwargs:
            return df.query(" and ".join(f"{k} == {v}" for k, v in kwargs.items()))
        return df


class MetaData(ABC):
    def pre(self, *args, **kwargs) -> dict:
        return {}

    def post(self, pre, result, *args, **kwargs) -> dict:
        return pre

    @property
    @abstractmethod
    def keys(self) -> dict[str, type]:
        ...

    @property
    @abstractmethod
    def name(self) -> str:
        ...


class Runtime(MetaData):
    def pre(self, *_, **__):
        return {'timestart': time.time()}

    def post(self, pre, *_, **__):
        pre['timestop'] = time.time()
        pre['walltime'] = pre['timestop'] - pre['timestart']
        return pre

    name: str = 'runtime'
    keys = {
            'timestart': float,
            'timestop': float,
            'walltime': float,
    }


class ResultDigest(MetaData):
    def post(self, pre, result, *_, **__):
        return {**pre, "result": digest(result)}

    keys = {"result": str}
    name = "resultdigest"
