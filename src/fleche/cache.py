from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Self

from .digest import digest
from .metadata import MetaDB
from . import storage


class SaveError(Exception):
    pass


class BaseCache(ABC):

    @abstractmethod
    def save(self, invocation, result, metadata):
        ...

    @abstractmethod
    def load(self, key):
        ...

    def contains(self, key: str) -> bool:
        try:
            self.load(key)
            return True
        except KeyError:
            return False

    def transfer(self, other: 'Cache'):
        # TODO: when migrating results up, we will need to think about what happens to conflicting metadata
        # probably transfering items should just pop them off the lower cache, therefore the only reason this could
        # happen is if a user runs the same function in two separate caches and then combines them.  In this case self
        # should win, because its intuitive even if a bit dangerous
        # TODO: make a design choice: is storage or metadata sovereign?
        # for now: storage is king because that's the most important part
        for key in self.storage.list():
            other.save(key, *self.load(key))

    def push(self, cache: 'BaseCache') -> 'CacheStack':
        return CacheStack((cache, self))

    def metadb(self, metadb) -> 'MetaCache':
        return MetaCache(self, metadb)


@dataclass
class Cache(BaseCache):
    storage: storage.Storage

    def save(self, invocation, result, metadata):
        self.storage.save(digest(result), result)
        self.storage.save(digest(invocation), (digest(result), metadata))

    def load(self, key):
        return self.storage.load(key)


@dataclass
class MetaCache(BaseCache):
    cache: BaseCache
    metadb: MetaDB

    def save(self, invocation, result, metadata):
        self.cache.save(invocation, result, metadata)
        self.metadb.save(digest(invocation), metadata)

    def load(self, key):
        return self.cache.load(key)


@dataclass(frozen=True)
class ReadOnlyCache(BaseCache):
    """A cache that can only be read from."""
    cache: BaseCache

    def save(self, invocation, result, metadata):
        raise SaveError(self, result)

    def load(self, key):
        return self.cache.load(key)


@dataclass(frozen=True)
class CacheStack(BaseCache):
    """
    Represents a combination of caches.

    Saving will always hit the lowest level, while loading will traverse up.
    """
    stack: tuple[Cache]

    def save(self, invocation, result, metadata):
        self.stack[0].save(invocation, result, metadata)

    def load(self, key):
        for cache in self.stack:
            try:
                return cache.load(key)
            except KeyError:
                continue
        else:
            raise KeyError(key)

    def push(self, cache: BaseCache) -> Self:
        return CacheStack((cache, *self.stack))
