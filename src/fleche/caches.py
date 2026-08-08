from abc import ABC, abstractmethod
import contextlib
import logging
import random
from dataclasses import dataclass, replace, field
from typing import Iterable, Any, Callable, Literal, overload

import pandas as pd

from . import digest as _digest
from .digest import Digest  # type hint convenience
from . import storage
from .storage.base import _apply_shrink, _resolve_prefix, Intent, OperationContext
from .storage.destructuring import HasChildDigests, HasScannableDigests
from .storage.thread_safe import PerKeyLockMixin, _PicklableRLock
from .call import Call, LazyCall, PreparedCall, QueryCall
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


class BaseCache(OperationContext):

    @classmethod
    def from_config(cls, config: "dict[str, Any] | list[dict[str, Any]]") -> "BaseCache":
        """Build a cache from a config dict/list.

        Thin wrapper around :func:`fleche.config.cache_from_config`.  The
        concrete cache type is chosen from the *shape* of ``config`` (plain
        cache, stack, pool, size-limited, read-only, ``template`` shorthand,
        ...), so the returned instance is not necessarily of type ``cls``.

        :mod:`fleche.config` is imported lazily here because it imports this
        module at import time; a module-level import would be circular.
        """
        from . import config as _config
        return _config.cache_from_config(config)

    def prepare(self, call: Call) -> PreparedCall:
        """Admit *call* to this cache: seal its lookup key before the body runs.

        The first half of the two-phase save protocol.  Caches that own a
        value storage (:class:`~fleche.caches.Cache`) override this to stash the argument
        values now, so the recorded identity describes the arguments as they
        were at call time, even if the body later mutates them.  This base
        implementation is the digest-only admission for caches that cannot
        (or must not) write ahead of the body — read-only views, aggregates
        without their own storage; ``digest(x) == values.save(x)``, so both
        forms seal the same key.

        Finish the returned :class:`~fleche.call.PreparedCall` with exactly
        one of :meth:`~fleche.call.PreparedCall.commit` or
        :meth:`~fleche.call.PreparedCall.abandon`.
        """
        return PreparedCall(digested=call.digest(), cache=self)

    @abstractmethod
    def save(self, call: PreparedCall | Call) -> str:
        """File a call record.

        Takes either a live :class:`~fleche.call.Call` — values are stored on the spot, the
        one-shot form — or a :class:`~fleche.call.PreparedCall` whose argument
        values were already stored by :meth:`~fleche.caches.BaseCache.prepare` and whose pending result
        is stored now, as returned."""
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
        self.query().transfer(other, pop=pop, overwrite=overwrite)

    def _transfer_one(self, c: LazyCall, *, overwrite: bool = False) -> bool:
        """Atomically replay one call into this cache, honouring ``overwrite``.

        Holds this cache's per-key operation context across the whole
        ``contains`` → ``save`` sequence, so the "skip if already present"
        decision cannot race a concurrent writer (the #452
        ``contains``→``save`` TOCTOU).  The context is reentrant, so
        ``contains`` / ``save`` re-entering it for the same key do not deadlock.
        Keeping this on the cache (rather than in
        :meth:`~fleche.query.QueryIterator.transfer`) means the query layer
        only ever calls public cache methods, and each cache encapsulates its
        own locking — :class:`CacheWrapper` and :class:`CacheStack` override
        :meth:`~fleche.storage.base.OperationContext._operation_context` so wrapper/stack targets lock their *real*
        inner :class:`~fleche.caches.Cache` rather than the no-op base context.

        Args:
            c: the call to transfer; fetched from its source cache only on the
                non-conflict path, so a skipped transfer pays no deserialisation.
            overwrite: if True, write even when a conflicting entry exists.

        Returns:
            ``True`` if the call was written, ``False`` if it was skipped
            because a conflicting entry already exists.
        """
        key = c.to_lookup_key()
        with self._operation_context(key):
            if not overwrite and self.contains(key):
                return False
            self.save(c.fetch())
            return True

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
            key (str or :class:`~fleche.digest.Digest`): the short digest prefix to expand

        Returns:
            :class:`~fleche.digest.Digest`: the full-length digest

        Raises:
            KeyError: if the key is not found
            :class:`~fleche.storage.base.AmbiguousDigestError`: if the prefix matches more than one entry
        """
        ...

    @overload
    def shrink(self, key: Digest | str, /) -> Digest: ...
    @overload
    def shrink(self, key: Digest | str, /, *keys: Digest | str) -> "tuple[Digest, ...]": ...
    def shrink(self, *keys: Digest | str) -> "Digest | tuple[Digest, ...]":
        """
        Find the shortest substring(s) that unambiguously reference each call.

        With a single key, returns one :class:`~fleche.digest.Digest`.  With multiple keys,
        returns a tuple of :class:`~fleche.digest.Digest` in the same order as the inputs;
        the batched form lets sub-storages list their keys once instead of
        per-key, which matters on backends where listing is expensive (e.g.
        SQL, filesystem).

        Each input key must belong to *one* of the sub-storages (call or
        value).  Mixing call keys and value keys in a single call is
        undefined behaviour — the result depends on internal partitioning
        order and may change without notice.

        .. warning::

            This is a property of how many values there are in your storage!
            A key returned from this function may become ambigious in the future when more values are added.
            Do not rely on this function in your programs, it is provided as a convenience for users only!

        Args:
            *keys (str or :class:`~fleche.digest.Digest`): one or more keys to shorten

        Returns:
            :class:`~fleche.digest.Digest` (single key) or tuple of :class:`~fleche.digest.Digest` (multiple)

        Raises:
            :class:`~fleche.storage.base.AmbiguousDigestError`: if no shorter key is possible for any input
        """
        return _apply_shrink(self._shrink, keys)

    @abstractmethod
    def _shrink(self, *keys: Digest | str) -> "tuple[Digest, ...]":
        """Partition and shrink all keys; always returns a same-length tuple of short digests."""
        ...

    @abstractmethod
    def _query(self, call: QueryCall) -> Iterable[LazyCall]: ...

    def query(self, template: "call.QueryCall | None" = None, **kwargs) -> query.QueryIterator:
        """Query the cache for matching calls.

        Accepts either a :class:`~fleche.call.QueryCall` as the first positional argument,
        or the same keyword arguments that :class:`~fleche.call.QueryCall` accepts.
        Omitted fields default to ``None`` (wildcard).  Passing both a template and
        keyword arguments raises :class:`TypeError`.

        Examples::

            cache.query(name="my_func")
            cache.query(name="my_func", arguments={"x": 1})
            cache.query(QueryCall(name="my_func"))  # existing form still works
            cache.query()  # all calls

        Returns:
            :class:`~fleche.query.QueryIterator`
        """
        if template is None:
            template = call.QueryCall(**kwargs)
        elif kwargs:
            raise TypeError("Cannot pass keyword arguments when a QueryCall template is provided")

        def _safe_iter():
            try:
                yield from self._query(template)
            except _digest.Indigestible as e:
                logger.warning("No hash for query argument: %s", e.args[0])
        return query.QueryIterator(_safe_iter, cache=self)

    def table(
        self,
        arguments: Iterable[str] | str | Literal[True] = (),
        results=False,
        shrink_keys: bool = True,
    ) -> pd.DataFrame:
        """Return a pandas DataFrame summarizing cached calls via query().

        This implementation uses a fully-wildcard Call template to retrieve
        all calls through ``self.query`` and then flattens metadata keys into
        top-level columns for convenience.

        By default, arguments and results are elided.

        The DataFrame index will be the lookup key (digest) of each call.
        Columns are:

        - ``name``: the function name
        - ``module``: the module name
        - ``result``: if the *results* argument is ``True``
        - metadata fields are flattened and added as columns directly

        If given argument names collide with any of the above columns, they are prefixed by ``a_``.
        Only requested arguments are loaded from cache.

        Args:
            arguments: add the given arguments (of the queried calls) as columns to the table.
                Pass ``True`` to add all arguments, or a single string as a shortcut for a
                one-element tuple.
            results (bool): if True, add results of queried calls to table
            shrink_keys (bool): if True (default), shrink each index entry to
                its shortest unambiguous prefix.  Set to ``False`` to keep
                full-length digests.

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
        return self.query(tpl).table(arguments=arguments, results=results, shrink_keys=shrink_keys)

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


def _combine_shrink(key: "Digest | str", results: "Iterable[Digest]") -> "Digest":
    """Reduce sub-storage shrink results to the longest (safest) prefix.

    Raises:
        KeyError: if no results were found.
    """
    all_results = list(results)
    if not all_results:
        raise KeyError(key)
    return max(all_results, key=len)


@dataclass(frozen=True)
class Cache(PerKeyLockMixin, BaseCache):
    values: storage.ValueStorage
    calls: storage.CallStorage

    def load_value(self, key):
        with self._operation_context(key):
            return self.values.load(key)

    def prepare(self, call: Call) -> PreparedCall:
        # Stash the arguments *now*, before the function body runs, so the
        # record cannot end up keyed on post-mutation content.  No cache-level
        # lock: the keys are only known once the value storage has digested
        # each value, and value storages carry their own per-key locking.
        return PreparedCall(digested=call.stash(self.values), cache=self)

    def save(self, call: PreparedCall | Call) -> str:
        key = call.to_lookup_key()
        with self._operation_context(key):
            try:
                if isinstance(call, Call):
                    # One-shot form: nothing was stored ahead of time, and with
                    # no function body between digesting and filing there is
                    # nothing to drift.
                    digested = call.stash(self.values)
                elif isinstance(call, PreparedCall):
                    # Committed result, stored as returned; the arguments must
                    # NOT be re-saved here — reading them after the body ran is
                    # exactly the post-mutation keying prepare exists to
                    # prevent.
                    digested = call.resolve(self.values)
                else:
                    # Already fully digested: file as-is.
                    digested = call
            except storage.SaveError as e:
                raise Rejected(e)
            return self.calls.save(digested)

    def load(self, key: str) -> LazyCall:
        with self._operation_context(key):
            return self.calls.load(key).fetch(self)

    def contains(self, key: str) -> bool:
        with self._operation_context(key):
            return self.calls.contains(key)

    def expand(self, key: Digest | str) -> Digest:
        with self._operation_context(key):
            results = []
            for sub in (self.calls, self.values):
                try:
                    results.append(sub.expand(key))
                except KeyError:
                    pass
            return _resolve_prefix(key, results, dedupe=True)

    def _shrink(self, *keys: Digest | str) -> "tuple[Digest, ...]":
        call_keys: list = []
        value_keys: list = []
        for k in keys:
            if self.calls.contains(k):
                call_keys.append(k)
            elif self.values.contains(k):
                value_keys.append(k)
            else:
                raise KeyError(k)
        results: dict = {}
        for sub, ks in ((self.calls, call_keys), (self.values, value_keys)):
            if not ks:
                continue
            r = sub._shrink(*ks)
            for k, s in zip(ks, r):
                results[k] = s
        return tuple(results[k] for k in keys)

    def _query(self, call: QueryCall) -> Iterable[LazyCall]:
        """Query for cached calls that match a template and return decoded results.

        This delegates to the underlying :meth:`~fleche.storage.base.CallStorage.query` using the provided template ``call``. Any digested
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
                        "Failed to load matching call %s with %s! Indicates corrupt cache.",
                        c.to_lookup_key(),
                        err,
                        exc_info=True,
                )

    def evict(self, key: str | Digest) -> None:
        with self._operation_context(key):
            self.calls.evict(key)

    def redigest(self) -> None:
        """Ensures consistent cache keys in case digest function changed.

        This may take time depending on cache size."""
        for key in self.calls.list():
            loaded = self.load(key).fetch()
            new_key = loaded.to_lookup_key()
            if new_key == key:
                continue
            # Hold the per-key locks for both the old and the new key so the
            # "save under the new key, then evict the old key" pair is atomic
            # with respect to concurrent readers probing either key (#451).
            # Without this, a reader could observe the call under both keys
            # (transient duplication) or under neither (transient miss),
            # depending on the interleaving.  The locks are reentrant, so the
            # nested acquisitions inside save()/evict() are fine; we sort the
            # keys to impose a consistent acquisition order and avoid deadlock.
            first, second = sorted((key, new_key))
            with self._operation_context(first), self._operation_context(second):
                # instantiate values too
                self.save(loaded)
                self.evict(key)

    def gc(self, load: bool = True) -> set[Digest]:
        """Evict value entries not reachable from any stored call.

        Brute-force mark-and-sweep: walks every call record to build the set
        of directly-referenced value digests, then transitively follows
        destructured sub-references (via :meth:`~fleche.storage.destructuring.DestructuringMixin.child_digests`
        on storages that satisfy :class:`~fleche.storage.destructuring.HasChildDigests`), and evicts every
        ``values`` key outside the reachable
        set.  Call records are left untouched.

        Args:
            load: when ``True`` (the default) the transitive walk deserializes
                each value to find its sub-references.  Pass ``False`` to read
                them off the serialized entries instead (via
                :meth:`~fleche.storage.destructuring.DestructuringMixin.scan_child_digests`
                on storages that satisfy
                :class:`~fleche.storage.destructuring.HasScannableDigests`) —
                what makes ``gc`` runnable against a *foreign* store whose
                payload classes are not importable here.  Only the value walk
                is affected; call records hold nothing but digests, strings and
                JSON metadata, so they load either way.

        Returns:
            The set of digests that were evicted from value storage.

        Raises:
            fleche.storage.scan.ScanUnsupported: with ``load=False`` on a value storage whose
                serialized form cannot be scanned.  Nothing is evicted — an
                unreadable reference graph must never be read as "unreachable".
        """
        reachable: set[Digest] = set()
        for key in self.calls.list():
            try:
                dc = self.calls.load(key)
            except KeyError:
                continue
            if isinstance(dc.result, Digest):
                reachable.add(dc.result)
            for v in dc.arguments.values():
                if isinstance(v, Digest):
                    reachable.add(v)

        # A storage that offers no reference query at all leaves `reachable` as
        # the direct call references and skips the transitive walk entirely.
        children_of: "Callable[[Digest], set[Digest]]" = lambda _key: set()
        if load and isinstance(self.values, HasChildDigests):
            children_of = self.values.child_digests
        elif not load and isinstance(self.values, HasScannableDigests):
            children_of = self.values.scan_child_digests

        frontier = set(reachable)
        while frontier:
            key = frontier.pop()
            try:
                children = children_of(key)
            except KeyError:
                continue
            new = children - reachable
            reachable |= new
            frontier |= new

        evicted: set[Digest] = set()
        for key in list(self.values.list()):
            if key not in reachable:
                try:
                    self.values.evict(key)
                    evicted.add(key)
                except KeyError:
                    continue
        return evicted


@dataclass(frozen=True)
class CacheWrapper(BaseCache):
    """Forwarding base class: all BaseCache methods delegate to ``self.cache``.

    Combine with behaviour mixins (ReadOnlyMixin, FilteringMixin) to build
    concrete wrapper classes without redeclaring ``cache``.
    """

    cache: BaseCache

    def prepare(self, call: Call) -> PreparedCall:
        # The inner cache decides how the arguments are stored; rebinding the
        # cache makes the eventual commit go through *this* wrapper's ``save``,
        # so wrapper policy (read-only, filtering, size limits) still applies.
        return replace(self.cache.prepare(call), cache=self)

    def save(self, call: PreparedCall | Call) -> str:
        return self.cache.save(call)

    def load(self, key: str) -> LazyCall:
        return self.cache.load(key)

    def load_value(self, key: str) -> Any:
        return self.cache.load_value(key)

    def contains(self, key: str) -> bool:
        return self.cache.contains(key)

    def evict(self, key: str | Digest) -> None:
        self.cache.evict(key)

    def expand(self, key: Digest | str) -> Digest:
        return self.cache.expand(key)

    def _shrink(self, *keys: Digest | str) -> "tuple[Digest, ...]":
        return self.cache._shrink(*keys)

    def _query(self, call: QueryCall) -> Iterable[LazyCall]:
        return self.cache.query(call)

    @contextlib.contextmanager
    def _operation_context(self, key, *, intent: Intent = Intent.WRITE):
        # A wrapper and its inner cache are never accessed independently — every
        # forwarding method above delegates to ``self.cache`` — so forwarding the
        # context makes that already-true fact explicit.  Without it the wrapper
        # would inherit the no-op base context, leaving ``_transfer_one``'s
        # check-then-save unguarded for wrapper targets (the #452 gap).  The
        # inner lock is reentrant, so the forwarding ``contains`` / ``save`` /
        # ``shrink`` re-entering it for the same key do not deadlock.
        with self.cache._operation_context(key, intent=intent):
            yield


class ReadOnlyMixin:
    """Read-only behaviour: ``save`` and ``evict`` raise :class:`Rejected`.

    Field-free and base-free, so it composes onto *any* cache layout — a
    single-cache wrapper (:class:`ReadOnlyCache`, :class:`FilteredCache`) or a
    multi-cache view (:class:`CachePool`).  Place it **first** in the bases so
    its ``save``/``evict`` win over a forwarding/aggregating implementation.

    It is also the marker ``_is_read_only()`` keys on, so any
    cache mixing it in is recognised as read-only by the SSH layer (which then
    short-circuits ``save``/``evict`` without a round-trip).
    """

    def save(self, call: PreparedCall | Call):
        raise Rejected(self, call)

    def evict(self, key: str | Digest) -> None:
        raise Rejected("Cannot evict from a read-only cache", self, key)

    def prepare(self, call: Call) -> "PreparedCall":
        # Digest-only admission, restated from BaseCache because this mixin is
        # base-free and must beat CacheWrapper.prepare in the MRO: nothing is
        # stashed, the key is still sealed, and the commit is rejected by
        # ``save`` above — the body runs and returns uncached.
        return PreparedCall(digested=call.digest(), cache=self)


@dataclass(frozen=True)
class ReadOnlyCache(ReadOnlyMixin, CacheWrapper):
    """A cache that can only be read from."""


@dataclass(frozen=True)
class FilteringMixin(CacheWrapper):
    """Filters ``load`` and ``_query`` results by a predicate."""

    predicate: Callable[[Call | LazyCall], bool]

    def load(self, key: str) -> LazyCall:
        lc = self.cache.load(key)
        if not self.predicate(lc):
            raise KeyError(key)
        return lc

    def _query(self, call: QueryCall) -> Iterable[LazyCall]:
        for c in self.cache.query(call):
            if self.predicate(c):
                yield c


@dataclass(frozen=True)
class FilteredCache(ReadOnlyMixin, FilteringMixin):
    """A read-only view of a cache that only exposes calls matching a predicate."""


@dataclass(frozen=True)
class RefreshingCache(CacheWrapper):
    """A cache that forces re-execution by always missing on load.

    It forwards saves and value loads to an underlying cache, allowing
    new results to be stored while ensuring that existing ones are
    ignored for the duration of its use.

    This is necessary to handle nested fleche calls during a rerun,
    otherwise forcing them to re-execute would be awkward.
    """

    def load(self, key: str) -> LazyCall:
        raise KeyError(key)

    def contains(self, key: str) -> bool:
        return False


class _MultiCache(BaseCache):
    """Shared read fan-out for caches that aggregate several member caches.

    Subclasses expose their members via :attr:`_members` and choose their own
    *write* / :meth:`BaseCache.load` policy.  Everything that only **reads** across the
    members — :meth:`BaseCache.contains`, :meth:`BaseCache.load_value`, :meth:`BaseCache.expand`,
    :meth:`_shrink`, :meth:`_query` — plus the three private traversal helpers
    lives here, so :class:`CacheStack` (an ordered, writable hierarchy) and
    :class:`CachePool` (an unordered, read-only collection) share one
    implementation of the fan-out.

    Each traversal helper implements one of the recurring patterns:

    - :meth:`_first_hit` — return on the first success; raise if all miss.
    - :meth:`_collect` — gather every success; caller combines the results.
    - :meth:`_foreach` — apply to every member; swallow expected refusals.
    """

    @property
    @abstractmethod
    def _members(self) -> "tuple[BaseCache, ...]":
        """The member caches to fan out over, in traversal order."""
        ...

    def load_value(self, key):
        return self._first_hit(lambda c: c.load_value(key))

    def contains(self, key: str) -> bool:
        return any(cache.contains(key) for cache in self._members)

    def expand(self, key: Digest | str) -> Digest:
        return _resolve_prefix(key, self._collect(lambda c: c.expand(key)), dedupe=True)

    def _shrink(self, *keys: Digest | str) -> "tuple[Digest, ...]":
        per_key: dict = {k: [] for k in keys}
        for cache in self._members:
            present = [k for k in keys if cache.contains(k)]
            if not present:
                continue
            r = cache._shrink(*present)
            for k, s in zip(present, r):
                per_key[k].append(s)
        out_list = []
        for k in keys:
            if not per_key[k]:
                raise KeyError(k)
            out_list.append(_combine_shrink(k, per_key[k]))
        return tuple(out_list)

    def _query(self, call: QueryCall) -> Iterable[LazyCall]:
        """Aggregate query results across the members, avoiding duplicates.

        The members are queried in order.  Results are deduplicated by their
        lookup key (via ``Call.to_lookup_key()``) and yielded in the order they
        are first seen.

        Args:
            call: A template ``Call`` where ``None`` fields act as wildcards.

        Yields:
            Call | LazyCall: Matching calls from any member, without duplicates.
        """
        seen = set()
        for cache in self._members:
            for c in cache.query(call):
                k = c.to_lookup_key()
                if k in seen:
                    continue
                seen.add(k)
                yield c

    # ------------------------------------------------------------------
    # Private traversal helpers — three patterns that recur across the
    # public fan-out methods.  New multi-cache operations should be
    # expressed as a one-liner over whichever helper fits.
    # ------------------------------------------------------------------

    def _first_hit(self, op: Callable[["BaseCache"], Any], *, exc: type[BaseException] = KeyError) -> Any:
        """Return the first successful result from iterating the members.

        Invokes ``op(cache)`` on each member in :attr:`_members` in order and
        returns immediately when a call does not raise *exc*.  If every member
        raises *exc* the exception is re-raised.

        This is the **first-hit-wins** pattern: used when any single cache can
        satisfy the request and earlier members are preferred (e.g.
        :meth:`BaseCache.load_value`).  The caller supplies the per-cache operation as a
        lambda so the key (or other closure state) is always available in the
        traceback without adding an extra helper argument.

        Args:
            op:  Callable that accepts a single :class:`BaseCache` and returns
                 the desired result.  Called at most once per member.
            exc: Exception *class* treated as a cache miss.  Defaults to
                 :class:`KeyError`.  Must be a single type (not a tuple)
                 because it is also used in the ``raise`` at the end.

        Raises:
            BaseException: whatever *exc* is bound to, if every member
                raises it.
        """
        for cache in self._members:
            try:
                return op(cache)
            except exc:
                continue
        raise exc

    def _collect(self, op: Callable[["BaseCache"], Any], *, exc: type[BaseException] = KeyError) -> list:
        """Collect one result per member, skipping misses.

        Invokes ``op(cache)`` on every member in :attr:`_members` and appends
        each non-raising result to a list.  Members that raise *exc* are
        silently skipped; all other exceptions propagate normally.

        This is the **collect-and-combine** pattern: used when all members may
        hold relevant data and the caller needs to aggregate results before
        returning (e.g. :meth:`BaseCache.expand` and :meth:`_shrink`, which pass the
        collected list to ``_resolve_prefix``/``_combine_shrink``).

        Args:
            op:  Callable that accepts a single :class:`BaseCache` and returns
                 a result to collect.  Called exactly once per member.
            exc: Exception *class* to treat as a miss and skip.  Defaults to
                 :class:`KeyError`.

        Returns:
            A list of all non-raising results in member order.  May be empty
            when every member misses; the caller is responsible for handling
            that case (typically by raising :class:`KeyError`).
        """
        out = []
        for cache in self._members:
            try:
                out.append(op(cache))
            except exc:
                pass
        return out

    def _foreach(
        self,
        op: Callable[["BaseCache"], None],
        *,
        exc: type[BaseException] | tuple[type[BaseException], ...] = (Rejected, KeyError),
    ) -> None:
        """Apply an operation to every member, swallowing refusals.

        Invokes ``op(cache)`` on every member in :attr:`_members`
        unconditionally.  Exceptions of type *exc* are caught and discarded;
        any other exception propagates normally.

        This is the **apply-everywhere** pattern: used when an operation should
        be attempted on all members regardless of whether individual caches
        support it (e.g. :meth:`CacheStack.evict`, where read-only caches raise
        :class:`Rejected` and empty caches raise :class:`KeyError`, and both
        are expected non-fatal outcomes).

        Args:
            op:  Callable that accepts a single :class:`BaseCache`.  Its return
                 value is ignored.  Called exactly once per member.
            exc: Exception type(s) to swallow.  Defaults to
                 ``(Rejected, KeyError)`` — the two standard refusal signals
                 used across the cache hierarchy.  Pass a tuple to swallow
                 multiple types.
        """
        for cache in self._members:
            try:
                op(cache)
            except exc:
                pass


@dataclass(frozen=True)
class CacheStack(PerKeyLockMixin, _MultiCache):
    """A combination of caches with a shared traversal policy.

    Saving always targets the lowest level (``stack[0]``); loading traverses
    from ``stack[0]`` upward and back-fills any hit into ``stack[0]``.  The
    back-fill is serialized per key (via :class:`~fleche.storage.thread_safe.PerKeyLockMixin`) so that
    concurrent loads of the same missing key do not all run the base cache's
    non-atomic check-evict-save at once.

    All multi-cache fan-out is inherited from :class:`_MultiCache`'s three
    private traversal helpers.
    """

    stack: tuple[BaseCache, ...]

    @property
    def _members(self) -> "tuple[BaseCache, ...]":
        return self.stack

    def __post_init__(self):
        for c in self.stack:
            if isinstance(c, CacheStack):
                raise ValueError("CacheStack cannot be nested inside another CacheStack")

    def save(self, call: PreparedCall | Call) -> str:
        return self.stack[0].save(call)

    def prepare(self, call: Call) -> PreparedCall:
        # Writes always land on stack[0] (matching save), so that is where the
        # arguments are stashed and where the commit files directly — this
        # stack's own ``save`` is a pure forward to the same place.
        return self.stack[0].prepare(call)

    @contextlib.contextmanager
    def _operation_context(self, key, *, intent: Intent = Intent.WRITE):
        # Saves always land on ``stack[0]``, so that is the only member that
        # needs the real (write) lock; every other member is entered with
        # ``Intent.READ``, a no-op today (reserved for a future shared lock).
        # This makes ``_transfer_one``'s check-then-save atomic against the
        # bottom cache where the write goes — closing the #452 TOCTOU for stack
        # targets — while ``contains`` still fans out across the whole stack.
        # ``stack[0]`` forwards through any wrapper to its real inner lock.
        #
        # NOTE: before ``Intent.READ`` is ever made a genuine *shared* lock,
        # members must be entered in a canonical (lock-identity) order — two
        # stacks sharing leaves in inverted order (``(A, B)`` vs ``(B, A)``) on
        # the same key would otherwise deadlock.  While READ is a no-op only
        # ``stack[0]`` is ever locked, so a single lock cannot deadlock.
        with contextlib.ExitStack() as es:
            for i, cache in enumerate(self.stack):
                es.enter_context(
                    cache._operation_context(key, intent=intent if i == 0 else Intent.READ)
                )
            yield

    def load(self, key) -> LazyCall:
        for i, cache in enumerate(self.stack):
            try:
                lc = cache.load(key)
                if i > 0:
                    self._backfill(key, lc)
                return lc
            except KeyError:
                continue
        raise KeyError(key)

    def _backfill(self, key, lc: LazyCall) -> None:
        """Transfer a hit from a higher cache into the base cache.

        Serialized per key so that concurrent loads of the same missing key do
        not all run the base cache's non-atomic check-evict-save at once.  All
        concurrent loaders block on the per-key :meth:`~fleche.storage.base.OperationContext._operation_context` lock;
        the first one past the lock does the transfer, and every later waiter
        finds the key already present via :meth:`~BaseCache.contains` and returns
        without repeating the save.
        """
        with self._operation_context(key):
            if self.stack[0].contains(key):
                return
            try:
                self.save(lc.fetch())
                logger.info("Transferred hit for %s from higher cache to base cache", key)
            except Rejected as e:
                logger.warning("Failed to transfer hit for %s to base cache: %s", key, e)

    def push(self, cache: BaseCache) -> "CacheStack":
        return CacheStack((cache, *self.stack))

    def evict(self, key: str | Digest) -> None:
        self._foreach(lambda c: c.evict(key))


@dataclass(frozen=True)
class CachePool(ReadOnlyMixin, _MultiCache):
    """A read-only collection of caches queried as one.

    Where :class:`CacheStack` is an *ordered, writable* hierarchy (saves land
    on ``stack[0]`` and hits back-fill downward), a ``CachePool`` is an
    *unordered, read-only* aggregate: it never writes to any member.  Use it to
    expose several independent caches — a teammate's results directory, a
    shared read-only archive, last month's run — as a single cache you can
    :meth:`BaseCache.load`, :meth:`BaseCache.contains`, :meth:`BaseCache.query`, :meth:`BaseCache.expand` and
    :meth:`BaseCache.shrink` against without risking a write to any of them.

    All reads fan out across :attr:`caches`:

    - :meth:`BaseCache.load` / :meth:`BaseCache.load_value` — first member to hold the key wins.
    - :meth:`BaseCache.contains` — true if *any* member holds the key.
    - :meth:`BaseCache.query` — union across members, deduplicated by lookup key.
    - :meth:`BaseCache.expand` / :meth:`BaseCache.shrink` — combined across members.

    Read-only-ness is inherited from :class:`ReadOnlyMixin` (so ``save`` and
    ``evict`` raise :class:`Rejected`, and the SSH layer recognises the pool as
    read-only); the members are kept exactly as the caller supplied them.
    Unlike :class:`CacheStack`, ``load`` does **not** back-fill a hit anywhere,
    so members are never mutated as a side effect of reading.  The member order
    only decides which cache's copy is returned on a :meth:`BaseCache.load` collision;
    every member is an equally valid read source.
    """

    caches: tuple[BaseCache, ...]

    @property
    def _members(self) -> "tuple[BaseCache, ...]":
        return self.caches

    def load(self, key: str) -> LazyCall:
        return self._first_hit(lambda c: c.load(key))


class SizeLimitedMixin(BaseCache):
    """Mixin that enforces a maximum number of cached calls with random eviction.

    Combine this with :class:`~fleche.caches.Cache` (mixin first in MRO) to get a size-limited
    cache::

        @dataclass
        class SizeLimitedCache(SizeLimitedMixin, Cache):
            max_size: int

    When a new call is saved and the number of cached calls exceeds ``max_size``,
    a call record is selected for eviction via :meth:`SizeLimitedMixin._pick_eviction_target`.
    Value storage is intentionally left untouched.

    The concrete class must provide a ``max_size`` integer, which is provided
    automatically when mixed with :class:`~fleche.caches.Cache`.
    """

    max_size: int
    _lock: _PicklableRLock = field(init=False, repr=False, compare=False)
    _keys: set[str] = field(init=False, repr=False, compare=False)

    def __post_init__(self, *args, **kwargs):
        if hasattr(super(), '__post_init__'):
            super().__post_init__(*args, **kwargs)  # ty: ignore
        object.__setattr__(self, '_lock', _PicklableRLock())
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

    def save(self, call: PreparedCall | Call) -> str:
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
    """A :class:`~fleche.caches.Cache` that enforces a maximum number of cached calls.

    When a new call is saved and the number of cached calls exceeds ``max_size``,
    a call record is selected for eviction via :meth:`SizeLimitedMixin._pick_eviction_target`.
    The default policy evicts uniformly at random; override
    :meth:`SizeLimitedMixin._pick_eviction_target` to change this.

    Args:
        values: Value storage (forwarded to :class:`~fleche.caches.Cache`).
        calls: Call storage (forwarded to :class:`~fleche.caches.Cache`).
        max_size: Maximum number of calls to keep.
    """

    max_size: int
