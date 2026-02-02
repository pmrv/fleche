from dataclasses import dataclass

from .metadata import MetaDB
from .storage import Storage


@dataclass
class Cache:
    metadata: MetaDB
    storage: Storage
