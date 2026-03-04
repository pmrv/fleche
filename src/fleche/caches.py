from abc import ABC, abstractmethod
import logging
from dataclasses import dataclass, asdict, replace
from copy import copy
from typing import Self, Iterable, Any, Union

import pandas as pd

from . import digest as _digest
from .digest import Digest  # type hint convenience
from . import storage
from .call import Call, LazyCall

logger = logging.getLogger("fleche.cache")


class Rejected(Exception):
    """Cache refused to cache the call for some reason or other."""
    pass


# backwards compat imports
# from breaking introduced in 0.4.0
DigestedIterable = storage.base.DigestedIterable
DigestedDict = storage.base.DigestedDict


class BaseCache(ABC):

    @abstractmethod
    def save(self, call: Union["Call", "LazyCall"]) -> str:
        ...

    @abstractmethod
    def load(self, key: str, lazy: bool = False) -> Call | LazyCall:
        ...

    @abstractmethod
    def load_value(self, key: str) -> Any:
        ...

    def contains(self, key: str) -> bool:
        try:
            self.load(key, lazy=True)
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
        return CacheStack((cache, self))  # type: ignore

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

    @abstractmethod
    def query(self, call: Call, lazy: bool = False) -> Iterable[Call | LazyCall]: ...

    def table(self) -> pd.DataFrame:
        """Return a pandas DataFrame summarizing cached calls via query().

        This implementation uses a fully-wildcard Call template to retrieve
        all calls through ``self.query`` and then flattens metadata keys into
        top-level columns for convenience.

        Arguments and results are elided.

        The DataFrame index will be the lookup key (digest) of each call.

        Returns:
            :class:`pandas.DataFrame`: table of all calls on cache
        """
        # Query all calls using a wildcard template; rely on concrete caches to
        # handle any necessary decoding (e.g., Cache decodes values on query()).
        tpl = Call(name=None, arguments=None, metadata=None, module=None, version=None, result=None)  # type: ignore

        rows: dict[str, dict[str, Any]] = {}
        # Use lazy=False to ensure we have actual values for the table
        for c in self.query(tpl, lazy=True):
            row = {
                    prop: getattr(c, prop) for prop in ("name", "module", "metadata")
            }
            md = row.pop("metadata", {}) or {}
            # Flatten each metadata name's dict into the row
            for data in md.values():
                if isinstance(data, dict):
                    row.update(data)
            rows[str(c.to_lookup_key())] = row

        return pd.DataFrame.from_dict(rows, orient="index")


@dataclass
class Cache(BaseCache):
    values: storage.Storage
    calls: storage.CallStorage | storage.Storage

    def __post_init__(self):
        if isinstance(self.calls, storage.Storage):
            self.calls = storage.CallStorageAdapter(self.calls)

        if not isinstance(self.values, storage.DestructuringStorage):
            self.values = storage.DestructuringStorage(self.values)

    def load_value(self, key):
        if not isinstance(key, Digest):
            return key

        return self.values.load(key)

    def _handle_args_save(self, value):
        if isinstance(value, Digest):
            return value
        # for arguments saving is not critical, substitute digest and move on
        try:
            return self.values.save(value)
        except storage.SaveError:
            logger.warning("Failed to save argument: %s", value)
            return _digest.digest(value)

    def _handle_args_load(self, key):
        if not isinstance(key, Digest):
            return key  # found a simple value
        try:
            return self.load_value(key)
        except KeyError:
            # if value is not in storage, leave the digest in place
            return key

    def save(self, call: Union["Call", "LazyCall"]) -> str:
        call = copy(call)
        try:
            call.result = self.values.save(call.result)  # type: ignore
            call.arguments = {  # type: ignore
                k: self._handle_args_save(v) for k, v in call.arguments.items()
            }
        except storage.SaveError as e:
            raise Rejected(e)

        return self.calls.save(call)  # type: ignore

    def _decode_call(self, call: Call, lazy: bool = False) -> Call | LazyCall:
        if lazy:
            return LazyCall(
                name=call.name,
                _arguments=call.arguments,
                _result=call.result,
                _cache=self,
                metadata=call.metadata,
                module=call.module,
                version=call.version,
                code_digest=call.code_digest
            )
        call.arguments = {k: self._handle_args_load(v) for k, v in call.arguments.items()}
        call.result = self.load_value(call.result)
        return call

    def load(self, key: str, lazy: bool = False) -> Call | LazyCall:
        call = self.calls.load(key)
        return self._decode_call(call, lazy=lazy)

    def shrink(self, key: Digest | str) -> Digest:
        return self.calls.shrink(key)

    def query(self, call: Call, lazy: bool = False) -> Iterable[Call | LazyCall]:
        """Query for cached calls that match a template and return decoded results.

        This delegates to the underlying :meth:`CallStorage.query` using the provided template ``call``. Any digested
        argument values and the result are decoded via this cache's value storage before yielding.

        Args:
            call: A ``Call`` instance used as a template; fields set to ``None``
                act as wildcards. For arguments and result, comparisons follow
                digest semantics (i.e., values are matched by their digest).
            lazy: If True, return LazyCall instances instead of Call instances.

        Yields:
            Call | LazyCall: Matching calls with arguments and result decoded from digests
            where possible.
        """
        # Delegate to underlying call storage, but first expand possible value digests and decode any digested
        # arguments/results before yielding to the caller (same semantics as load()).
        def maybe_expand(value):
            if isinstance(value, Digest):
                return self.values.expand(value)
            else:
                return value
        call = replace(
                call,
                arguments={
                    k: maybe_expand(v)
                           for k, v in call.arguments.items()
                } if call.arguments is not None else {},
                result=maybe_expand(call.result),
        )
        for c in self.calls.query(call):  # type: ignore
            try:
                yield self._decode_call(c, lazy=lazy)
            except Exception as err:
                logger.error(f"Failed to load matching call {c.to_lookup_key()}! Indicates corrupt cache.")

    def redigest(self) -> None:
        """Ensures consistent cache keys in case digest function changed.

        This may take time depending on cache size."""
        for key in self.calls.list():
            call = self.load(key)
            if call.to_lookup_key() != key:
                # instantiate values too
                self.save(call)
                self.calls.evict(key)


@dataclass(frozen=True)
class ReadOnlyCache(BaseCache):
    """A cache that can only be read from."""
    cache: BaseCache

    def save(self, call: Union["Call", "LazyCall"]) -> str:
        raise Rejected(self, call)

    def load(self, key, lazy: bool = False):
        return self.cache.load(key, lazy=lazy)

    def shrink(self, key: Digest | str) -> Digest:
        return self.cache.shrink(key)

    def load_value(self, key):
        return self.cache.load_value(key)

    def query(self, call: Call, lazy: bool = False) -> Iterable[Call | LazyCall]:
        """Forward queries to the wrapped cache.

        Args:
            call: A template ``Call`` where ``None`` fields act as wildcards.
            lazy: If True, return LazyCall instances.

        Yields:
            Call | LazyCall: Results yielded by the wrapped cache's ``query`` method.
        """
        return self.cache.query(call, lazy=lazy)


@dataclass(frozen=True)
class CacheStack(BaseCache):
    """
    Represents a combination of caches.

    Saving will always hit the lowest level, while loading will traverse up.
    """
    stack: tuple[Cache, ...]

    def save(self, call: Union["Call", "LazyCall"]) -> str:
        return self.stack[0].save(call)

    def load(self, key, lazy: bool = False):
        for cache in self.stack:
            try:
                return cache.load(key, lazy=lazy)
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

    def push(self, cache: "BaseCache") -> "CacheStack":
        return CacheStack((cache, *self.stack))  # type: ignore

    def shrink(self, key: Digest | str) -> Digest:
        return sorted([c.shrink(key) for c in self.stack], key=len)[-1]  # type: ignore

    def query(self, call: Call, lazy: bool = False) -> Iterable[Call | LazyCall]:
        """Aggregate query results across the stack, avoiding duplicates.

        The caches are queried from bottom to top. Results are deduplicated by
        their lookup key (via ``Call.to_lookup_key()``) and yielded in the
        order they are first seen.

        Args:
            call: A template ``Call`` where ``None`` fields act as wildcards.
            lazy: If True, return LazyCall instances.

        Yields:
            Call | LazyCall: Matching calls from any cache in the stack, without duplicates.
        """
        seen = set()
        for cache in self.stack:
            for c in cache.query(call, lazy=lazy):
                k = c.to_lookup_key()
                if k in seen:
                    continue
                seen.add(k)
                yield c
