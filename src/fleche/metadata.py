from abc import ABC, abstractmethod
from dataclasses import dataclass, asdict
import time
from typing import Any

import pandas as pd

from .digest import digest
from .invocation import Invocation


class MetaDB(ABC):
    """Interface for databases that keep metadata."""
    @abstractmethod
    def save(self, digest: str, metadata: dict[str, dict[str, Any]]) -> None:
        """Save a given metadata entry."""
        ...

    @abstractmethod
    def load(self, digest: str) -> dict[str, dict[str, Any]]:
        """Load a given metadata entry."""
        ...

    @abstractmethod
    def table(self, **kwargs: Any) -> pd.DataFrame:
        """Return a display-friendly table of all metadata entries.

        Entries can be filtered using the kwargs."""
        ...


@dataclass
class PandasDB(MetaDB):
    """
    A concrete implementation of MetaDB using Pandas DataFrames to store metadata.
    Each metadata type (e.g., 'runtime', 'resultdigest') is stored in its own DataFrame.
    """
    tables: dict[str, pd.DataFrame]

    def save(self, digest: str, metadata: dict[str, dict[str, Any]]) -> None:
        """
        Saves metadata for a given digest. Each metadata entry is added to its
        corresponding DataFrame. If a DataFrame for a metadata type does not exist,
        it will be created.

        Args:
            digest (str): The digest key associated with the metadata.
            metadata (dict[str, dict[str, Any]]): A dictionary where keys are metadata
                                                  names (e.g., 'runtime') and values
                                                  are dictionaries of metadata attributes.
        """
        for name, data in metadata.items():
            df = pd.DataFrame([data], index=[digest])
            if name in self.tables:
                self.tables[name] = pd.concat([self.tables[name], df])
            else:
                self.tables[name] = df

    def load(self, digest: str) -> dict[str, dict[str, Any]]:
        """
        Loads metadata for a given digest.

        Args:
            digest (str): The digest key of the metadata to load.

        Returns:
            dict[str, dict[str, Any]]: A dictionary containing the loaded metadata,
                                       structured by metadata name.
        """
        return {m: t.loc[digest].to_dict() for m, t in self.tables.items() if digest in t.index}

    def table(self, **kwargs: Any) -> pd.DataFrame:
        """
        Returns a display-friendly table of all metadata entries, optionally filtered
        by keyword arguments.

        Args:
            **kwargs (Any): Keyword arguments for filtering the metadata table.
                            e.g., column_name=value.

        Returns:
            pd.DataFrame: A DataFrame containing the metadata, potentially filtered.
        """
        # join all tables on index
        if not self.tables:
            return pd.DataFrame()

        df = pd.concat(self.tables.values(), axis=1)
        if kwargs:
            for k, v in kwargs.items():
                df = df[df[k] == v]
        return df


class MetaData(ABC):
    """Abstract base class for defining metadata types."""
    def pre(self, invocation: Invocation) -> dict[str, Any]:
        """
        Hook for collecting metadata before the function execution.

        Args:
            invocation (Invocation): The invocation object of the decorated function.

        Returns:
            dict[str, Any]: A dictionary of metadata collected before execution.
        """
        return {}

    def post(self, pre: dict[str, Any], result: Any, invocation: Invocation) -> dict[str, Any]:
        """
        Hook for collecting metadata after the function execution.

        Args:
            pre (dict[str, Any]): Metadata collected during the pre-execution phase.
            result (Any): The result of the decorated function.
            invocation (Invocation): The invocation object of the decorated function.

        Returns:
            dict[str, Any]: A dictionary of metadata collected after execution.
        """
        return {}

    @property
    @abstractmethod
    def keys(self) -> dict[str, type]:
        """
        Defines the schema of the metadata, mapping metadata keys to their expected types.

        Returns:
            dict[str, type]: A dictionary representing the metadata schema.
        """
        ...

    @property
    @abstractmethod
    def name(self) -> str:
        """
        The unique name of this metadata type.

        Returns:
            str: The name of the metadata type.
        """
        ...


class Runtime(MetaData):
    """
    Metadata type for capturing runtime information, such as start time, stop time, and wall time.
    """
    def pre(self, invocation: Invocation) -> dict[str, Any]:
        """
        Records the start time before function execution.
        """
        return {'timestart': time.time()}

    def post(self, pre: dict[str, Any], result: Any, invocation: Invocation) -> dict[str, Any]:
        """
        Records the stop time and calculates the wall time after function execution.
        """
        return {
            'timestop': (t := time.time()),
            'walltime': t - pre['timestart'],
        }

    name: str = 'runtime'
    keys: dict[str, type] = {
            'timestart': float,
            'timestop': float,
            'walltime': float,
    }


class Digest(MetaData):
    """
    Metadata type for storing the digest of the function's result.
    """
    def pre(self, invocation: Invocation) -> dict[str, Any]:
        return {
            "arguments":
                {i: digest(a) for i, a in enumerate(invocation.args)}
                | {k: digest(v) for k, v in invocation.kwargs.items()}
        }

    def post(self, pre: dict[str, Any], result: Any, invocation: Invocation) -> dict[str, Any]:
        """
        Calculates and stores the digest of the function's result.
        """
        return {"result": digest(result)}

    name: str = "digest"
    keys: dict[str, type] = {"result": str}


class InvocationInfo(MetaData):
    def pre(self, invocation: Invocation) -> dict[str, Any]:
        pre = asdict(invocation)
        pre.pop("args")
        pre.pop("kwargs")
        return pre

    name: str = "invocation"
    keys = {
            "name":  str,
            "module":  str,
            "version":  int,
    }


@dataclass
class Tags(MetaData):
    tags: dict[str, Any]

    def pre(self, invocation: Invocation) -> dict[str, Any]:
        return self.tags.copy()

    name: str = "tags"

    @property
    def keys(self):
        return {k: type(v) for k, v in self.tags.items()}
