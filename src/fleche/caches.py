from abc import ABC, abstractmethod
from dataclasses import dataclass, asdict
from copy import copy
from typing import Self, Iterable, Any

import pandas as pd

from .digest import digest, Digest
from .metadata import MetaDB
from . import storage
from .call import Call


class Rejected(Exception):
    """Cache refused to cache the call for some reason or other."""
    pass


class BaseCache(ABC):

    @abstractmethod
    def save(self, value) -> str:
        ...

    @abstractmethod
    def load(self, key: str) -> Call:
        ...

    @abstractmethod
    def load_value(self, key: str) -> Any:
        ...

    def contains(self, key: str) -> bool:
        try:
            self.load(key)
            return True
        except KeyError:
            return False

    # def transfer(self, other: 'Cache'):
    #     # TODO: when migrating results up, we will need to think about what happens to conflicting metadata
    #     # probably transfering items should just pop them off the lower cache, therefore the only reason this could
    #     # happen is if a user runs the same function in two separate caches and then combines them.  In this case self
    #     # should win, because its intuitive even if a bit dangerous
    #     # TODO: make a design choice: is storage or metadata sovereign?
    #     # for now: storage is king because that's the most important part
    #     for key in self.storage.list():
    #         other.save(key, *self.load(key))

    def push(self, cache: 'BaseCache') -> 'CacheStack':
        return CacheStack((cache, self))

    def metadb(self, metadb) -> 'MetaCache':
        return MetaCache(self, metadb)

    @abstractmethod
    def shrink(self, key: Digest | str) -> Digest:
        """
        Find the shortest substring that is still an unambigious reference to the same call.

        .. warning::

            This is a property of how many values there are in your storage!
            A key returned from this function may become ambigious in the future when more values are added.
            Do not rely on this function in your programs, it is provided as a convenience for users only!

        Args:
            key (str or :class:`Digest`): the key to shorten

        Returns:
            :class:`Digest`: shortest key possible

        Raises:
            :class:`AmbiguousDigestError`: if no shorter key is possible
        """
        ...


class Digested(ABC):
    @abstractmethod
    def underlying(self):
        ...

    # mess with our hash to ensure that we are referentially transparent with respect to the underlying list.
    # For the replacement of the 'real' list with the 'digested' list to be invisible to caches, they must hash to the
    # same values.
    def __digest__(self):
        return digest(self.underlying())


@dataclass
class DigestedIterable(Digested):
    items: Iterable

    def underlying(self):
        return self.items


@dataclass
class DigestedDict(Digested):
    items: dict

    def underlying(self):
        return self.items


@dataclass
class Cache(BaseCache):
    values: storage.Storage
    calls: storage.Storage

    def _recursive_value_save(self, value):
        match value:
            case list() | tuple():
                return self.values.save(
                        DigestedIterable(type(value)(self._recursive_value_save(v) for v in value))
                )
            case dict():
                return self.values.save(
                        DigestedDict(
                            {self._recursive_value_save(k): self._recursive_value_save(v)
                                for k, v in value.items()}
                        )
                )
            case _:
                return self.values.save(value)

    def load_value(self, key):
        if not isinstance(key, Digest):
            return key
        try:
            value = self.values.load(key)
        except KeyError:
            return self.load(key).result

        match value:
            case DigestedIterable(items=items):
                value = type(items)(self.load_value(v) for v in items)
            case DigestedDict(items=items):
                value = {
                        self.load_value(k): self.load_value(v)
                        for k, v in value.items.items()
                }
        return value

    def _handle_args_save(self, value):
        # if value is 'simple' leave it in the call storage to be dealt with there
        if isinstance(value, (str, float, int)):
            return value
        # for arguments saving is not critical, substitute digest and move on
        try:
            return self._recursive_value_save(value)
        except storage.SaveError:
            print("WARNING NO ARG SAVE:", value)
            return digest(value)

    def _handle_args_load(self, key):
        if not isinstance(key, Digest):
            return key  # found a simple value
        try:
            return self.values.load(key)
        except KeyError:
            # if value is not in storage, leave the digest in place
            return key

    def save(self, inv: Call) -> str:
        inv = copy(inv)
        try:
            inv.result = self._recursive_value_save(inv.result)
            inv.args = tuple(self._handle_args_save(a) for a in inv.args)
            inv.kwargs = {k: self._handle_args_save(v) for k, v in inv.kwargs.items()}
        except storage.SaveError as e:
            raise Rejected(e)

        return self.calls.save(inv, key=digest(inv.to_lookup()))

    def load(self, key: str) -> Call:
        call = self.calls.load(key)
        call.args = tuple(self._handle_args_load(a) for a in call.args)
        call.kwargs = {k: self._handle_args_load(v) for k, v in call.kwargs.items()}
        call.result = self.load_value(call.result)
        return call

    def shrink(self, key: Digest | str) -> Digest:
        return self.calls.shrink(key)

    def table(self) -> pd.DataFrame:
        calls = [asdict(self.calls.load(k)) for k in self.calls.list()]
        for call in calls:
            metadata = call.pop('metadata')
            for data in metadata.values():
                call.update(data)
        return pd.DataFrame(calls)


@dataclass
class MetaCache(BaseCache):
    cache: BaseCache
    metadb: MetaDB

    def save(self, inv: Call) -> str:
        self.cache.save(inv)
        self.metadb.save(digest(inv), inv.metadata)

    def load(self, key):
        return self.cache.load(key)

    def shrink(self, key: Digest | str) -> Digest:
        return self.cache.shrink(key)

    def load_value(self, key):
        return self.cache.load_value(key)



@dataclass(frozen=True)
class ReadOnlyCache(BaseCache):
    """A cache that can only be read from."""
    cache: BaseCache

    def save(self, inv: Call):
        raise Rejected(self, inv)

    def load(self, key):
        return self.cache.load(key)

    def shrink(self, key: Digest | str) -> Digest:
        return self.cache.shrink(key)

    def load_value(self, key):
        return self.cache.load_value(key)



@dataclass(frozen=True)
class CacheStack(BaseCache):
    """
    Represents a combination of caches.

    Saving will always hit the lowest level, while loading will traverse up.
    """
    stack: tuple[Cache]

    def save(self, inv: Call):
        self.stack[0].save(inv)

    def load(self, key):
        for cache in self.stack:
            try:
                return cache.load(key)
            except KeyError:
                continue
        else:
            raise KeyError(key)

    def load_value(self, key):
        for cache in self.stack:
            try:
                return cache.load_value(key)
            except KeyError:
                continue
        else:
            raise KeyError(key)

    def push(self, cache: BaseCache) -> Self:
        return CacheStack((cache, *self.stack))

    def shrink(self, key: Digest | str) -> Digest:
        return sorted([c.shrink(key) for c in self.stack], key=len)[-1]
