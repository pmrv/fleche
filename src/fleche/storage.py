from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from cloudpickle import loads, dumps


class Storage(ABC):

    @abstractmethod
    def save(self, digest, value):
        ...

    @abstractmethod
    def load(self, digest):
        ...

    @abstractmethod
    def list(self) -> Iterable[str]:
        ...


@dataclass
class MemoryStorage(Storage):
    storage: {}

    def save(self, digest, value):
        self.storage[digest] = value

    def load(self, digest):
        return self.storage[digest]

    def list(self) -> Iterable[str]:
        return self.storage.keys()


@dataclass
class CloudpickleFileStorage(Storage):
    root: Path

    def __post_init__(self):
        self.root = Path(self.root)
        self.root.mkdir(exist_ok=True)

    def save(self, digest, value):
        with open(self.root / digest, "wb") as f:
            f.write(dumps(value))

    def load(self, digest):
        with open(self.root / digest, "rb") as f:
            return loads(f.read())

    def list(self) -> Iterable[str]:
        return (p.name for p in self.root.iterdir())
