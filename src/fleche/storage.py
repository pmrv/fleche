from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Any

from cloudpickle import loads, dumps
from bagofholding import H5Bag


class Storage(ABC):
    """Abstract base class for defining storage mechanisms."""

    @abstractmethod
    def save(self, digest: str, value: Any) -> None:
        """
        Saves a value to storage using a given digest as a key.

        Args:
            digest (str): The digest (hash) to use as the key for storing the value.
            value (Any): The value to be stored.
        """
        ...

    @abstractmethod
    def load(self, digest: str) -> Any:
        """
        Loads a value from storage using a given digest as a key.

        Args:
            digest (str): The digest (hash) corresponding to the stored value.

        Returns:
            Any: The loaded value.

        Raises:
            KeyError: If no value is found for the given digest.
        """
        ...

    @abstractmethod
    def list(self) -> Iterable[str]:
        """
        Lists all digests (keys) currently present in the storage.

        Returns:
            Iterable[str]: An iterable of all digests stored.
        """
        ...


@dataclass
class Memory(Storage):
    """
    A concrete implementation of Storage that stores values in an in-memory dictionary.
    """
    storage: dict[str, Any]

    def save(self, digest: str, value: Any) -> None:
        """
        Saves a value to the in-memory storage.

        Args:
            digest (str): The digest (hash) to use as the key for storing the value.
            value (Any): The value to be stored.
        """
        self.storage[digest] = value

    def load(self, digest: str) -> Any:
        """
        Loads a value from the in-memory storage.

        Args:
            digest (str): The digest (hash) corresponding to the stored value.

        Returns:
            Any: The loaded value.

        Raises:
            KeyError: If no value is found for the given digest.
        """
        return self.storage[digest]

    def list(self) -> Iterable[str]:
        """
        Lists all digests (keys) currently present in the in-memory storage.

        Returns:
            Iterable[str]: An iterable of all digests stored.
        """
        return self.storage.keys()


@dataclass
class FileStorage(Storage):
    root: Path

    def __post_init__(self) -> None:
        """
        Ensures the root directory for storage exists.
        """
        self.root = Path(self.root)
        self.root.mkdir(exist_ok=True)

    def _path(self, digest: str) -> Path:
        return self.root / digest

    def list(self) -> Iterable[str]:
        """
        Lists all digests (filenames) currently present in the root directory.

        Returns:
            Iterable[str]: An iterable of all digests stored.
        """
        return (p.name for p in self.root.iterdir())


@dataclass
class CloudpickleFile(FileStorage):
    """
    A concrete implementation of Storage that stores values as files on the filesystem,
    using cloudpickle for serialization.
    """

    def save(self, digest: str, value: Any) -> None:
        """
        Saves a value to a file in the root directory, serialized using cloudpickle.

        Args:
            digest (str): The digest (hash) to use as the filename.
            value (Any): The value to be stored.
        """
        with open(self._path(digest), "wb") as f:
            f.write(dumps(value))

    def load(self, digest: str) -> Any:
        """
        Loads a value from a file in the root directory, deserialized using cloudpickle.

        Args:
            digest (str): The digest (hash) corresponding to the filename.

        Returns:
            Any: The loaded value.

        Raises:
            KeyError: If no file is found for the given digest.
        """
        try:
            with open(self._path(digest), "rb") as f:
                return loads(f.read())
        except FileNotFoundError:
            raise KeyError(digest) from None


@dataclass
class BagOfHoldingH5File(FileStorage):
    root: Path

    def save(self, digest: str, value: Any) -> None:
        H5Bag.save(value, self._path(digest))

    def load(self, digest: str) -> Any:
        return H5Bag(self._path(digest)).load()
