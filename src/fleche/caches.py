from abc import ABC, abstractmethod
import logging
from dataclasses import dataclass, replace, field, InitVar
from copy import copy
from typing import Iterable, Any, Callable, overload

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
    def save(self, call: Call) -> str:
        ...

    @overload
    def load(self, key: str, lazy: bool = False) -> Call:
        ...

    @overload
    def load(self, key: str, lazy: bool = True) -> LazyCall:
        ...

    @abstractmethod
    def load(self, key: str, lazy: bool = True) -> Call | LazyCall:
        ...

    @abstractmethod
    def load_value(self, key: str) -> Any: ...

    @abstractmethod
    def evict(self, key: str | Digest) -> None:
        ...

    def contains(self, key: str) -> bool:
        try:
            self.load(key, lazy=True)
            return True
        except KeyError:
            return False

    def transfer(self, other: "BaseCache", pop: bool = False) -> None:
        """Transfer all calls from this cache to another cache.

        Existing calls in the target cache may be overwritten by the transferred calls.

        Args:
            other: The destination cache.
            pop: If True, evict transferred keys from the source cache after moving.
        """
        # fmt: off
        tpl = Call(name=None, arguments=None, metadata=None, module=None, version=None, result=None)  # type: ignore
        # fmt: on
        for call in self.query(tpl, lazy=False):
            other.save(call)
            if pop and hasattr(self, "calls"):
                self.calls.evict(call.to_lookup_key())  # type: ignore

    def push(self, cache: "BaseCache") -> "CacheStack":
        return CacheStack((cache, self))

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
    def query(self, call: Call) -> Iterable[LazyCall]: ...

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
        # FIXME: We'll want a specific query call type at some point
        # fmt: off
        tpl = Call(name=None, arguments=None, metadata=None, module=None, version=None, result=None)  # type: ignore
        # fmt: on

        rows: dict[str, dict[str, Any]] = {}
        for c in self.query(tpl):
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

    def filter(
        self, predicate: Callable[[Call | LazyCall], bool] | Call
    ) -> "FilteredCache":
        """Create a read-only view of this cache that only exposes calls matching the predicate.

        Args:
            predicate: A function that takes a Call or LazyCall and returns True
                if it should be included in the new cache, or a Call object to
                use as a template.

        Returns:
            FilteredCache: A read-only view of the cache.
        """
        if isinstance(predicate, Call):
            predicate = predicate.matches

        return FilteredCache(self, predicate)


@dataclass
class Cache(BaseCache):
    values: storage.Storage
    calls: storage.CallStorage = field(init=False)

    _calls: InitVar[storage.CallStorage | storage.Storage]

    def __post_init__(self, _calls):
        if isinstance(_calls, storage.Storage):
            self.calls = storage.CallStorageAdapter(_calls)
        else:
            self.calls = _calls

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

    def save(self, call: Call) -> str:
        call = copy(call)
        try:
            call.result = self.values.save(call.result)
            call.arguments = {
                k: self._handle_args_save(v) for k, v in call.arguments.items()
            }
        except storage.SaveError as e:
            raise Rejected(e)

        return self.calls.save(call)

    @overload
    def _decode_call(self, call: Call, lazy: bool = False) -> Call: ...

    @overload
    def _decode_call(self, call: Call, lazy: bool = True) -> LazyCall: ...

    def _decode_call(self, call: Call, lazy: bool) -> Call | LazyCall:
        if lazy:
            return LazyCall(
                name=call.name,
                _arguments=call.arguments,
                _result=call.result,
                _cache=self,
                metadata=call.metadata,
                module=call.module,
                version=call.version,
                code_digest=call.code_digest,
            )

        call.arguments = {
            k: self._handle_args_load(v) for k, v in call.arguments.items()
        }
        call.result = self.load_value(call.result)
        return call

    @overload
    def load(self, key: str, lazy: bool = False) -> Call: ...

    @overload
    def load(self, key: str, lazy: bool = True) -> LazyCall: ...

    def load(self, key: str, lazy: bool = True) -> Call | LazyCall:
        call = self.calls.load(key)
        return self._decode_call(call, lazy)

    def contains(self, key: str) -> bool:
        return self.calls.contains(key)

    def shrink(self, key: Digest | str) -> Digest:
        return self.calls.shrink(key)

    def query(self, call: Call) -> Iterable[LazyCall]:
        """Query for cached calls that match a template and return decoded results.

        This delegates to the underlying :meth:`CallStorage.query` using the provided template ``call``. Any digested
        argument values and the result are decoded via this cache's value storage before yielding.

        Args:
            call: A ``Call`` instance used as a template; fields set to ``None``
                act as wildcards. For arguments and result, comparisons follow
                digest semantics (i.e., values are matched by their digest).

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
        for c in self.calls.query(call):
            try:
                yield self._decode_call(c, lazy=True)
            except Exception as err:
                logger.error(
                    f"Failed to load matching call {c.to_lookup_key()} with {err}! Indicates corrupt cache."
                )

    def evict(self, key: str | Digest) -> None:
        self.calls.evict(key)

    def redigest(self) -> None:
        """Ensures consistent cache keys in case digest function changed.

        This may take time depending on cache size."""
        for key in self.calls.list():
            call = self.load(key).fetch()  # ty: ignore
            if call.to_lookup_key() != key:
                # instantiate values too
                self.save(call)
                self.calls.evict(key)


@dataclass(frozen=True)
class ReadOnlyCache(BaseCache):
    """A cache that can only be read from."""

    cache: BaseCache

    def save(self, call: Call):
        raise Rejected(self, call)

    def load(self, key, lazy: bool = True):
        return self.cache.load(key, lazy=lazy)

    def shrink(self, key: Digest | str) -> Digest:
        return self.cache.shrink(key)

    def evict(self, key: str | Digest) -> None:
        raise Rejected("Cannot evict from a ReadOnlyCache", self, key)

    def load_value(self, key):
        return self.cache.load_value(key)

    def contains(self, key: str) -> bool:
        return self.cache.contains(key)

    def query(self, call: Call) -> Iterable[LazyCall]:
        """Forward queries to the wrapped cache.

        Args:
            call: A template ``Call`` where ``None`` fields act as wildcards.

        Yields:
            Call | LazyCall: Results yielded by the wrapped cache's ``query`` method.
        """
        return self.cache.query(call)


@dataclass(frozen=True)
class FilteredCache(ReadOnlyCache):
    """A read-only view of a cache that only exposes calls matching a predicate."""

    predicate: Callable[[Call | LazyCall], bool]

    def load(self, key, lazy: bool = True):
        call: LazyCall = self.cache.load(
            key, lazy=True
        )  # ty: ignore bug or I'm really tired
        if self.predicate(call):
            if not lazy:
                return call.fetch()
            return call
        raise KeyError(key)

    def query(self, call: Call) -> Iterable[LazyCall]:
        for c in self.cache.query(call):
            if self.predicate(c):
                yield c


@dataclass(frozen=True)
class RefreshingCache(BaseCache):
    """A cache that forces re-execution by always missing on load.

    It forwards saves and value loads to an underlying cache, allowing
    new results to be stored while ensuring that existing ones are
    ignored for the duration of its use.

    This is necessary to handle nested fleche calls during a rerun,
    otherwise forcing them to re-execute would be awkward.
    """

    cache: BaseCache

    def save(self, call: Call) -> str:
        return self.cache.save(call)

    @overload
    def load(self, key: str, lazy: bool = False) -> Call: ...

    @overload
    def load(self, key: str, lazy: bool = True) -> LazyCall: ...

    def load(self, key: str, lazy: bool = True) -> Call | LazyCall:
        raise KeyError(key)

    def load_value(self, key: str) -> Any:
        return self.cache.load_value(key)

    def contains(self, key: str) -> bool:
        return False

    def evict(self, key: str | Digest) -> None:
        self.cache.evict(key)

    def shrink(self, key: Digest | str) -> Digest:
        return self.cache.shrink(key)

    @overload
    def query(self, call: Call, lazy: bool = False) -> Iterable[Call]: ...

    @overload
    def query(self, call: Call, lazy: bool = True) -> Iterable[LazyCall]: ...

    def query(self, call: Call, lazy: bool = True) -> Iterable[Call | LazyCall]:
        return self.cache.query(call, lazy=lazy)


@dataclass(frozen=True)
class CacheStack(BaseCache):
    """
    Represents a combination of caches.

    Saving will always hit the lowest level, while loading will traverse up.
    """

    stack: tuple[BaseCache, ...]

    def save(self, call: Call):
        self.stack[0].save(call)

    def load(self, key, lazy: bool = True):
        for i, cache in enumerate(self.stack):
            try:
                call = cache.load(key, lazy=lazy)
                if i > 0:
                    try:
                        self.save(call.fetch() if lazy else call)  # ty: ignore
                        logger.info("Transferred hit for %s from higher cache to base cache", key)
                    except Rejected as e:
                        logger.warning("Failed to transfer hit for %s to base cache: %s", key, e)
                return call
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

    def contains(self, key: str) -> bool:
        return any(cache.contains(key) for cache in self.stack)

    def push(self, cache: BaseCache) -> "CacheStack":
        return CacheStack((cache, *self.stack))

    def evict(self, key: str | Digest) -> None:
        for cache in self.stack:
            try:
                cache.evict(key)
            except (Rejected, KeyError):
                continue

    def shrink(self, key: Digest | str) -> Digest:
        return max([c.shrink(key) for c in self.stack], key=len)  # ty: ignore upstream bug, already filled

    def query(self, call: Call) -> Iterable[LazyCall]:
        """Aggregate query results across the stack, avoiding duplicates.

        The caches are queried from bottom to top. Results are deduplicated by
        their lookup key (via ``Call.to_lookup_key()``) and yielded in the
        order they are first seen.

        Args:
            call: A template ``Call`` where ``None`` fields act as wildcards.

        Yields:
            Call | LazyCall: Matching calls from any cache in the stack, without duplicates.
        """
        seen = set()
        for cache in self.stack:
            for c in cache.query(call):
                k = c.to_lookup_key()
                if k in seen:
                    continue
                seen.add(k)
                yield c
