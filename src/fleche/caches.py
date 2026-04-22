from abc import ABC, abstractmethod
import logging
import random
import threading
from dataclasses import dataclass, replace, field
from typing import Iterable, Any, Callable, Literal

import pandas as pd

from . import digest as _digest
from .digest import Digest  # type hint convenience
from . import storage
from .call import Call, DigestedCall, LazyCall, QueryCall
from . import call
from . import query

logger = logging.getLogger("fleche.cache")


class Rejected(Exception):
    """Cache refused to cache the call for some reason or other."""
    pass


# backwards compat imports
# from breaking introduced in 0.4.0
DigestedIterable = storage.destructuring.DigestedIterable
DigestedDict = storage.destructuring.DigestedDict


class BaseCache(ABC):

    @abstractmethod
    def save(self, call: Call) -> str:
        ...

    @abstractmethod
    def load(self, key: str) -> LazyCall:
        ...

    @abstractmethod
    def load_value(self, key: str) -> Any: ...

    @abstractmethod
    def evict(self, key: str | Digest) -> None:
        ...

    def contains(self, key: str) -> bool:
        try:
            self.load(key)
            return True
        except KeyError:
            return False

    def transfer(self, other: "BaseCache", pop: bool = False, overwrite: bool = False) -> None:
        """Transfer all calls from this cache to another cache.

        Args:
            other: The destination cache.
            pop: If True, evict transferred keys from the source cache after moving.
            overwrite: If True, overwrite existing entries in the target cache.
                If False (default), skip entries that already exist in the target.
        """
        tpl = call.QueryCall(name=None, arguments=None, metadata=None, module=None, version=None, result=None)
        for c in self.query(tpl):
            c = c.fetch()
            key = c.to_lookup_key()
            conflict = not overwrite and other.contains(key)
            if not conflict:
                other.save(c)
            if pop:
                if conflict:
                    logger.warning(
                        "Not evicting %s from source: already exists in target and overwrite=False",
                        key,
                    )
                else:
                    self.evict(key)
                    
    def readonly(self) -> "ReadOnlyCache":
        """Return a read-only view of this cache."""
        return ReadOnlyCache(self)

    def push(self, cache: "BaseCache") -> "CacheStack":
        return CacheStack((cache, self))

    @abstractmethod
    def expand(self, key: Digest | str) -> Digest:
        """
        Expand a short digest prefix to its full-length digest.

        Args:
            key (str or :class:`Digest`): the short digest prefix to expand

        Returns:
            :class:`Digest`: the full-length digest

        Raises:
            KeyError: if the key is not found
            :class:`AmbiguousDigestError`: if the prefix matches more than one entry
        """
        ...

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
    def _query(self, call: call.QueryCall) -> Iterable[LazyCall]: ...

    def query(self, call: call.QueryCall) -> query.QueryIterator:
        def _safe_iter():
            try:
                yield from self._query(call)
            except _digest.Unhashable as e:
                logger.warning("No hash for query argument: %s", e.args[0])
        return query.QueryIterator(_safe_iter())

    def table(self, arguments: Iterable[str] | str | Literal[True] = (), results=False) -> pd.DataFrame:
        """Return a pandas DataFrame summarizing cached calls via query().

        This implementation uses a fully-wildcard Call template to retrieve
        all calls through ``self.query`` and then flattens metadata keys into
        top-level columns for convenience.

        By default, arguments and results are elided.

        The DataFrame index will be the lookup key (digest) of each call.
        Columns are:
            - `name`: the function name
            - `module`: the module name
            - 'result`: if `results` argument is `True`
            - metadata fields are flattened and added as columns directly

        If given argument names collide with any of the above columns, they are prefixed by 'a_'.
        Only requested arguments are loaded from cache.

        Args:
            arguments: add the given arguments (of the queried calls) as columns to the table.
                Pass ``True`` to add all arguments, or a single string as a shortcut for a
                one-element tuple.
            results (bool): if True, add results of queried calls to table

        Returns:
            :class:`pandas.DataFrame`: table of all calls on cache
        """
        tpl = call.QueryCall(
            name=None,
            arguments=None,
            metadata=None,
            module=None,
            version=None,
            result=None,
        )
        return self.query(tpl).table(arguments=arguments, results=results)

    def filter(self, predicate: Callable[[Call | LazyCall], bool] | QueryCall) -> 'FilteredCache':
        """Create a read-only view of this cache that only exposes calls matching the predicate.

        Args:
            predicate: A function that takes a Call or LazyCall and returns True
                if it should be included in the new cache, or a QueryCall object to
                use as a template.

        Returns:
            FilteredCache: A read-only view of the cache.
        """
        if isinstance(predicate, QueryCall):
            predicate = predicate.matches

        return FilteredCache(self, predicate)


def _combine_expand(key: "Digest | str", results: "Iterable[Digest]") -> "Digest":
    """Reduce sub-storage expand results to a single resolved digest.

    Raises:
        KeyError: if no results were found.
        AmbiguousDigestError: if results disagree on the full digest.
    """
    unique = sorted(set(results))
    if not unique:
        raise KeyError(key)
    if len(unique) == 1:
        return unique[0]
    m1, m2 = unique[0], unique[1]
    for i, (c1, c2) in enumerate(zip(m1, m2)):
        if c1 != c2:
            break
    else:
        i = min(len(m1), len(m2))
    raise storage.AmbiguousDigestError(
        f"Short digest {key} is ambiguous; expands to: {unique}; need at least {i + 1} characters."
    )


def _combine_shrink(key: "Digest | str", results: "Iterable[Digest]") -> "Digest":
    """Reduce sub-storage shrink results to the longest (safest) prefix.

    Raises:
        KeyError: if no results were found.
    """
    all_results = list(results)
    if not all_results:
        raise KeyError(key)
    return max(all_results, key=len)  # type: ignore


@dataclass(frozen=True)
class Cache(BaseCache):
    values: storage.ValueStorage
    calls: storage.CallStorage

    def load_value(self, key):
        if not isinstance(key, Digest):
            return key

        return self.values.load(key)

    def _handle_args_load(self, key):
        if not isinstance(key, Digest):
            return key  # found a simple value
        try:
            return self.load_value(key)
        except KeyError:
            # if value is not in storage, leave the digest in place
            return key

    def save(self, call: Call) -> str:
        try:
            digested = call.stash(self.values)
        except storage.SaveError as e:
            raise Rejected(e)
        return self.calls.save(digested)

    def load(self, key: str) -> LazyCall:
        return self.calls.load(key).fetch(self)

    def contains(self, key: str) -> bool:
        return self.calls.contains(key)

    def expand(self, key: Digest | str) -> Digest:
        results = []
        for sub in (self.calls, self.values):
            try:
                results.append(sub.expand(key))
            except KeyError:
                pass
        return _combine_expand(key, results)

    def shrink(self, key: Digest | str) -> Digest:
        results = []
        for sub in (self.calls, self.values):
            try:
                results.append(sub.shrink(key))
            except KeyError:
                pass
        return _combine_shrink(key, results)

    def _query(self, call: call.QueryCall) -> Iterable[LazyCall]:
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
                yield c.fetch(self)
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

    def load(self, key) -> LazyCall:
        return self.cache.load(key)

    def expand(self, key: Digest | str) -> Digest:
        return self.cache.expand(key)

    def shrink(self, key: Digest | str) -> Digest:
        return self.cache.shrink(key)

    def evict(self, key: str | Digest) -> None:
        raise Rejected("Cannot evict from a ReadOnlyCache", self, key)

    def load_value(self, key):
        return self.cache.load_value(key)

    def contains(self, key: str) -> bool:
        return self.cache.contains(key)

    def _query(self, call: call.QueryCall) -> Iterable[LazyCall]:
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

    def load(self, key) -> LazyCall:
        lc = self.cache.load(key)
        if not self.predicate(lc):
            raise KeyError(key)
        return lc

    def _query(self, call: call.QueryCall) -> Iterable[LazyCall]:
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

    def load(self, key: str) -> LazyCall:
        raise KeyError(key)

    def load_value(self, key: str) -> Any:
        return self.cache.load_value(key)

    def contains(self, key: str) -> bool:
        return False

    def evict(self, key: str | Digest) -> None:
        self.cache.evict(key)

    def expand(self, key: Digest | str) -> Digest:
        return self.cache.expand(key)

    def shrink(self, key: Digest | str) -> Digest:
        return self.cache.shrink(key)

    def _query(self, call: call.QueryCall) -> query.QueryIterator:
        return self.cache.query(call)


@dataclass(frozen=True)
class CacheStack(BaseCache):
    """
    Represents a combination of caches.

    Saving will always hit the lowest level, while loading will traverse up.
    """

    stack: tuple[BaseCache, ...]

    def __post_init__(self):
        for c in self.stack:
            if isinstance(c, CacheStack):
                raise ValueError("CacheStack cannot be nested inside another CacheStack")

    def save(self, call: Call):
        self.stack[0].save(call)

    def load(self, key) -> LazyCall:
        for i, cache in enumerate(self.stack):
            try:
                lc = cache.load(key)
                if i > 0:
                    try:
                        self.save(lc.fetch())
                        logger.info("Transferred hit for %s from higher cache to base cache", key)
                    except Rejected as e:
                        logger.warning("Failed to transfer hit for %s to base cache: %s", key, e)
                return lc
            except KeyError:
                continue
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

    def expand(self, key: Digest | str) -> Digest:
        results = []
        for c in self.stack:
            try:
                results.append(c.expand(key))
            except KeyError:
                pass
        return _combine_expand(key, results)

    def shrink(self, key: Digest | str) -> Digest:
        results = []
        for c in self.stack:
            try:
                results.append(c.shrink(key))
            except KeyError:
                pass
        return _combine_shrink(key, results)

    def _query(self, call: call.QueryCall) -> Iterable[LazyCall]:
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


class SizeLimitedMixin(BaseCache):
    """Mixin that enforces a maximum number of cached calls with random eviction.

    Combine this with :class:`Cache` (mixin first in MRO) to get a size-limited
    cache::

        @dataclass
        class SizeLimitedCache(SizeLimitedMixin, Cache):
            max_size: int

    When a new call is saved and the number of cached calls exceeds ``max_size``,
    a call record is selected for eviction via :meth:`_pick_eviction_target`.
    Value storage is intentionally left untouched.

    The concrete class must provide a ``max_size`` integer, which is provided
    automatically when mixed with :class:`Cache`.
    """

    max_size: int
    _lock: threading.RLock = field(init=False, repr=False, compare=False)
    _keys: set[str] = field(init=False, repr=False, compare=False)

    def __post_init__(self, *args, **kwargs):
        if hasattr(super(), '__post_init__'):
            super().__post_init__(*args, **kwargs)  # ty: ignore
        object.__setattr__(self, '_lock', threading.RLock())
        object.__setattr__(self, '_keys', {c.to_lookup_key() for c in self.query(call.QueryCall())})

    # ------------------------------------------------------------------
    # Eviction policy – override this to generalise to other strategies
    # (e.g. LRU, LFU, …).
    # ------------------------------------------------------------------

    def _pick_eviction_target(self, keys: list[str]) -> str:
        """Select the call to evict from a sample of cached call keys.

        The default implementation chooses uniformly at random.  Override this
        method to implement a different eviction policy without touching any
        other part of the class.

        Args:
            keys: A non-empty list of all tracked call keys.

        Returns:
            The key of the call that should be evicted.
        """
        return random.choice(keys)

    def _enforce_size_limit(self) -> None:
        """Evict call records until the cache is within ``max_size``."""
        with self._lock:
            while len(self._keys) > self.max_size:
                target = self._pick_eviction_target(list(self._keys))
                self.evict(target)

    def save(self, call: call.Call) -> str:
        with self._lock:
            key = super().save(call)
            self._keys.add(key)
            self._enforce_size_limit()
            return key

    def evict(self, key: str | _digest.Digest) -> None:
        with self._lock:
            super().evict(key)
            self._keys.discard(str(key))


@dataclass(frozen=True)
class SizeLimitedCache(SizeLimitedMixin, Cache):
    """A :class:`Cache` that enforces a maximum number of cached calls.

    When a new call is saved and the number of cached calls exceeds ``max_size``,
    a call record is selected for eviction via :meth:`_pick_eviction_target`.
    The default policy evicts uniformly at random; override
    :meth:`_pick_eviction_target` to change this.

    Args:
        values: Value storage (forwarded to :class:`Cache`).
        _calls: Call storage (forwarded to :class:`Cache`).
        max_size: Maximum number of calls to keep.
    """

    max_size: int
