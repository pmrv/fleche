from abc import ABC, abstractmethod
from dataclasses import dataclass
from copy import deepcopy
from pathlib import Path
from typing import Iterable, Any

from cloudpickle import loads, dumps
from bagofholding import H5Bag

from .digest import digest, Digest, DIGEST_LENGTH


class SaveError(Exception):
    pass


class AmbiguousDigestError(ValueError):
    pass


class Storage(ABC):
    """Abstract base class for defining storage mechanisms."""

    @abstractmethod
    def save(self, value: Any, key: Digest | None = None) -> str:
        """
        Saves a value to storage using its digest as a key

        Args:
            value (Any): The value to be stored.

        Returns:
            str: The key (digest) to use as the key for retrieving the value.
        """
        ...

    @abstractmethod
    def load(self, key: str) -> Any:
        """
        Loads a value from storage using a given key as a key.

        Args:
            key (str): The key (digest) corresponding to the stored value.

        Returns:
            Any: The loaded value.

        Raises:
            KeyError: If no value is found for the given key.
        """
        ...

    @abstractmethod
    def list(self) -> Iterable[str]:
        """
        Lists all keys (keys) currently present in the storage.

        Returns:
            Iterable[str]: An iterable of all keys stored.
        """
        ...

    def expand(self, key: Digest | str) -> Digest:
        """
        Expands a short-hand digest to the full length one.

        Args:
            key (:class:`Digest` | :class:`str`): The short-hand digest.

        Returns:
            :class:`Digest`: The full length digest.

        Raises:
            :class:`KeyError`: If no match is found.
            :class:`AmbiguousDigestError`: If multiple matches are found.
        """
        if len(key) >= DIGEST_LENGTH:
            return key
        if len(key) < 4:
            raise KeyError(key)

        matches = sorted([k for k in self.list() if k.startswith(key)])
        if not matches:
            raise KeyError(key)
        if len(matches) > 1:
            # find longest common prefix of the first two matches to find where they diverge
            m1, m2 = matches[0], matches[1]
            for i, (c1, c2) in enumerate(zip(m1, m2)):
                if c1 != c2:
                    break
            else:
                i = min(len(m1), len(m2))

            raise AmbiguousDigestError(f"Short digest {key} is ambiguous; need at least {i+1} characters.")
        return Digest(matches[0])


@dataclass
class Memory(Storage):
    """
    A concrete implementation of Storage that stores values in an in-memory dictionary.
    """
    storage: dict[str, Any]

    def save(self, value: Any, key: Digest | None = None) -> str:
        """
        Saves a value to the in-memory storage.

        Args:
            value (Any): The value to be stored.

        Returns:
            key (str): The key (digest) to use as the key for storing the value.
        """
        if key is None:
            key = digest(value)
        if key in self.storage:
            return key
        self.storage[key] = deepcopy(value)
        return key

    def load(self, key: str) -> Any:
        """
        Loads a value from the in-memory storage.

        Args:
            key (str): The key (digest) corresponding to the stored value.

        Returns:
            Any: The loaded value.

        Raises:
            KeyError: If no value is found for the given key.
        """
        if len(key) < DIGEST_LENGTH:
            key = self.expand(key)
        return deepcopy(self.storage[key])

    def list(self) -> Iterable[str]:
        """
        Lists all keys (keys) currently present in the in-memory storage.

        Returns:
            Iterable[str]: An iterable of all keys stored.
        """
        return self.storage.keys()


@dataclass
class FileStorage(Storage):
    root: Path

    def __post_init__(self) -> None:
        """
        Ensures the root directory for storage exists.
        """
        self.root = Path(self.root).expanduser().absolute().resolve()

    def _path(self, key: str) -> Path:
        self.root.mkdir(parents=True, exist_ok=True)
        return self.root / key

    def list(self) -> Iterable[str]:
        """
        Lists all keys (filenames) currently present in the root directory.

        Returns:
            Iterable[str]: An iterable of all keys stored.
        """
        self.root.mkdir(parents=True, exist_ok=True)
        return (p.name for p in self.root.iterdir())


@dataclass
class CloudpickleFile(FileStorage):
    """
    A concrete implementation of Storage that stores values as files on the filesystem,
    using cloudpickle for serialization.
    """

    def save(self, value: Any, key: Digest | None = None) -> str:
        """
        Saves a value to a file in the root directory, serialized using cloudpickle.

        Args:
            value (Any): The value to be stored.

        Returns:
            str: The key (digest) to use as the filename.
        """
        if key is None:
            key = digest(value)
        (self._path(key)).write_bytes(dumps(value))
        return key

    def load(self, key: str) -> Any:
        """
        Loads a value from a file in the root directory, deserialized using cloudpickle.

        Args:
            key (str): The key (digest) corresponding to the filename.

        Returns:
            Any: The loaded value.

        Raises:
            KeyError: If no file is found for the given key.
        """
        if len(key) < DIGEST_LENGTH:
            key = self.expand(key)
        try:
            return loads((self._path(key)).read_bytes())
        except FileNotFoundError:
            raise KeyError(key) from None


@dataclass
class BagOfHoldingH5File(FileStorage):

    def save(self, value: Any, key: Digest | None = None) -> Digest:
        if key is None:
            key = digest(value)
        try:
            H5Bag.save(value, self._path(key))
        except (ValueError, TypeError):  # h5py choked on something, pass it along
            raise SaveError(value) from None
        return key

    def load(self, key: str) -> Any:
        if len(key) < DIGEST_LENGTH:
            key = self.expand(key)
        try:
            return H5Bag(self._path(key)).load()
        except FileNotFoundError:
            raise KeyError(key) from None
