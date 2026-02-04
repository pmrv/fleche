from dataclasses import dataclass
from .metadata import MetaDB
from . import storage


@dataclass
class Cache:
    """
    Represents a cache composed of a metadata database and a storage mechanism.
    """
    metadata: MetaDB
    storage: storage.Storage

    def save(self, key, result, metadata):
        self.storage.save(key, result)
        self.metadata.save(key, metadata)
