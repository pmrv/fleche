# DEVELOPING.md

> **AI-agent reference.** This file is written for AI coding agents (Codex, Cursor, Aider, Claude, ...) working in or against this repo, linked from [AGENTS.md](../AGENTS.md) — not human-facing documentation.

Developing fleche's own source: commands, conventions, module map, architecture internals, test layout, and a map of open design work on the issue tracker.
If you just want to *use* fleche as a dependency instead, see [USAGE.md](USAGE.md).

## Commands

```bash
pip install -e ".[tests]"                              # install with test deps
pytest tests/                                          # all tests
pytest tests/unit/digest/test_digest.py::test_name     # single test
pytest -m smoke                                        # one-round-trip-per-optional-dep packaging sanity
ty check src/                                          # type check (CI: .github/workflows/ty.yml)
python benchmarks/run_benchmarks.py                    # benchmarks (writes benchmarks/results.csv)
```

Python `>=3.11,<3.15`.
No committed lint config;
`pyproject.toml` has no `[tool.ruff]`/`[tool.flake8]`.

Optional dep extras: `cloudpickle`,
`dill`,
`sqlalchemy`,
`bagofholding`,
`ssh` (cloudpickle — **hard-required** for `SshCache`'s wire protocol, not optional within that feature),
`executorlib`,
`docs`,
`tests` (the `tests` extra already pulls in cloudpickle/dill/sqlalchemy/bagofholding/attrs plus pytest/hypothesis/nbconvert/ipykernel/tabulate),
`ty` (pins the `ty` type-checker version run in CI).
`attrs` itself has no dedicated extra — it is only required to exercise the `attrs`-class digest/destructuring paths in tests;
runtime support degrades gracefully when `attrs` is missing.
Other optional deps are gated via `pyiron_snippets.import_alarm.ImportAlarm` — importing a backend without its extra installed raises at construction, not at module import.

## Conventions

- **Conventional Commits** are required (`feat:`/`fix:`/`docs:`/`test:`/`chore:`/`refactor:`, `!` or `BREAKING CHANGE:` for breaks).
  Release-please derives version bumps and changelog from `main`'s commit history — non-conforming messages are ignored by the release tooling.
  See [Commit messages](#commit-messages) below.
- Running inside a GitHub Action, **attribute commits to `claude[bot]`** (see [Commit attribution](#commit-attribution) below) so they aren't tagged to the workflow's PAT identity.
- If a task spans a separate issue/PR, keep the detailed response there;
  only post a quick link back to the original.
- Fail early when a dependency is missing;
  report the error rather than working around it.
- **One sentence per line** in `AGENTS.md` and `agents/*.md` (semantic line breaks).
  Start every sentence, and every `;`-separated clause, on its own line;
  break long `` `a`, `b`, `c` `` enumerations before each item.
  Never hard-wrap at a fixed column, and never join sentences back into one long line.
  Continuation lines of a list item are indented to the item's text.
  Markdown renders the lines as one paragraph, but a diff then touches only the sentences that changed, so concurrent PRs editing these files merge without conflicts.
  Keep tables to short cells;
  anything longer than a phrase belongs in a list.
  Run `python .github/workflows/reflow_agent_docs.py` after editing to apply this (`--check` only reports, exiting 1 if a file needs reflowing);
  it changes line breaks only, never words.

## Where to look

| Looking for | Start here |
|---|---|
| Decorator + helper attachment | `wrapper.py` |
| Hashing / digest dispatch | `digest.py` |
| Cache classes, mixins, stacks, GC | `caches.py` |
| Active cache, sticky context, metadata, `BoundWrapper` | `state.py` |
| TOML config + named-cache interning | `config.py` |
| Storage backends (memory / pickle / bagofholding / sql) | `storage/` |
| SSH remote forwarding | `remote.py` |
| Chainable queries | `query.py` |
| Test layout | [Test layout](#test-layout) |
| CI workflows | `.github/workflows/` (see [Other directories](#other-directories)) |
| What's been considered or rejected | [Design themes / open scope](#design-themes--open-scope-issue-tracker) |

---

## Quick Reference

This section is internals-level detail for developing fleche itself.
If you just want to *use* the library (decorator, config, backends), see [USAGE.md](USAGE.md) instead.

**What:** Persistent function cache (`@fleche()` decorator) — like `lru_cache` but survives restarts.
SHA256 content-based keys, pluggable backends.

**Entry points:** `wrapper.py` (decorator) → `call.py` (key building) → `digest.py` (hashing) → `caches.py` (cache objects) → `storage/` (backends).

**Active cache:** `ContextVar` in `state.py`, with **no default** — read it through `state.get_cache()`, which on `LookupError` falls back to `config.load_cache_config()` memoised in the module-level `_DEFAULTS` dict (same shape for metadata: `state.get_metadata()` → `config.load_default_metadata()`).
Resolution is therefore **lazy**: importing `fleche` doesn't touch the config files, and clearing `_DEFAULTS` makes the next access re-read them (that's how the config tests pick up a patched `XDG_CONFIG_HOME`).
`cache(c)` sets it and returns a sticky context manager — enter/exit as `with` to restore, or discard the return value to keep the change.
`cache()` with no args returns the current cache.
`cache(name_or_obj, stack=True)` builds a `CacheStack` with the new cache at `stack[0]` (the primary save/load target) and the previous active cache as fallback.
Config auto-discovery — the CWD→`$HOME` walk collecting and shallow-merging every `fleche.toml`, the XDG fallback, and the `[default] root = true` halt (ESLint-style;
the `_is_root_config` guard treats `[default]` as a source only when it is a table) — is spelled out once in [USAGE.md](USAGE.md#config-files--where-fleche-looks-and-whats-in-them).
Falls back to a `Cache(ValueMemory, CallMemory)` when no file is found.
The special names `cache("memory")` / `cache("void")` bypass the config file entirely;
`cache("default")` and `cache()` (no arg) resolve to the configured default cache.
Resolved caches are interned in `_live_caches` (`dict[str | None, BaseCache]`) keyed by the requested name — the default is *also* interned under `None` — so the same name always returns the same instance (and an `SshCache`/file backend isn't re-spawned/re-opened on each lookup).

**Public API (`fleche.__init__`):** `__version__`, `fleche`, `cache`, `meta`, `tags`, `project`, `BoundWrapper`, `Ignored`, `Required`, `D`, `wrap_executor`.
(Build a `BaseCache` from a config dict/list via the `BaseCache.from_config` classmethod — a thin wrapper over `config.cache_from_config`;
pass the result to `cache(...)` to activate it.) (`SshCache` is *not* here — reach it via `type="ssh"` config or `from fleche.remote import SshCache`.) `D(value)` returns a `Digest`: non-empty hex strings (≤64 chars, hex-only) pass through verbatim so they can be used as lookup keys;
anything else (including the empty string) is digested.
`Digest` args to a wrapped function are auto-expanded (loaded back to their value) by the cache before hashing.

**Backends (config `type` strings):** `"memory"`,
`"void"`,
`"pickle"` / `"cloudpickle"` / `"dill"` (filesystem with chosen serializer),
`"bagofholding_hdf"` (HDF5),
`"sql"` (SQLAlchemy, **calls only**),
`"ssh"` (whole-cache remote forwarding via `SshCache` — see `remote.py`).
Values and calls are stored separately so call records are queryable without deserializing heavy values.

**Key files:**

- `wrapper.py` — `@fleche()` decorator;
  re-exports `Ignored`/`Required` from `call.py`;
  `process_ignore_required_args` merges explicit `ignore=`/`require=` args into a `FunctionProfile` via `dataclasses.replace`;
  attaches `.call/.digest/.load/.contains/.query/.rerun/.bind` helpers (also mirrored on `.fleche.*`).
  `.bind(*args, **kwargs)` returns a `BoundWrapper`;
  when given args/kwargs it wraps the function in `functools.partial(...)` first, so the bound callable is a zero-arg closure with cache+metadata frozen.
  Helper construction is data-driven via `_PRE_WRAPPER_SPECS`/`_POST_WRAPPER_SPECS` module-level lists of `_HelperSpec` — add an entry there to register a new helper.
  **Two-phase save integration:** after `pre` metadata runs, the wrapper calls `cache.prepare(call)` to seal the record's identity, then executes the body — a `Rejected` at prepare falls back to a warning + uncached execute, any other prepare-time exception (storage fault, lost connection) also degrades to uncached, and a `BaseException` from the body triggers `prepared.abandon()` before re-raising.
  On success `prepared.commit(result, metadata)` files the record;
  a `None` result, an executor future that raises, or a `RefreshingCache` evict all also `abandon()`.
  `Future` results still deliver via `add_done_callback`, so the abandon call happens in the callback if the future itself explodes.
  `make_wrapper` also sets `wrapper.__digest__` to `partial(digest.digest, func)` (through `setattr`, so `ty` does not trip over the `@wraps`-typed wrapper): since closures are digested by their captured cells, a wrapper would otherwise digest by *fleche's* own closure — identical for every decorated function bar private mutable bookkeeping — so a decorated function passed as an argument would be keyed on fleche internals.
  With it, decoration is transparent (`digest(fleche()(f)) == digest(f)`).
  The in-flight dedup lock `_in_flight_lock` is a `storage.thread_safe._PicklableLock`, not a raw `threading.Lock`, so the wrapper closure survives cloudpickle-by-value (needed when a cross-process backend can't import the function by reference;
  pinned in `tests/regression/test_wrap_executor_cloudpickle_lock.py`).
- `digest.py` — `Digest(str)` (with `.expand`/`.shrink`);
  `digest()` (SHA256 hex);
  `Hook`, `add_hook`, `get_hooks`, `load_entry_points`;
  `Indigestible`;
  `DIGEST_LENGTH=64`.
  Built-in types are inline `match` cases in `_digest_bytes`, ordered roughly hot-path first: `int` (`bool ⊂ int`) → `Digest` (returns `value.encode()` so `digest(Digest("abc")) == "abc"`) → `str` → `None` → `Number` (`float`, `complex`, `Decimal`, `Fraction`, plus `np.integer`/`np.floating` which satisfy `numbers.Number` automatically;
  routed through `hash(value)` then recursed as int — a lossy encoding under which distinct numbers collide;
  see the numeric-digest bullet under **Bugs** below) → `bytes` → `np.ndarray` (dtype + shape + `tobytes`) → `np.bool_` (delegates to `digest(bool(value))`, because `np.bool_ ∉ Number` since numpy 1.20) → `pd.DataFrame` / `pd.Series` / `pd.Index` (must precede `Iterable` — DataFrame iterates over column names only, so the `Iterable` arm collides any two DataFrames with the same columns regardless of values;
  DataFrame folds in columns + per-column dtype + index, Series folds in name + dtype + index, Index folds in name + dtype;
  values are mixed via `pd.util.hash_pandas_object(...).values.tobytes()` — `index=False` on the DataFrame/Series arms (the Index arm passes no kwarg since Index has no index) because `hash_pandas_object` only mixes per-element value bytes and ignores name/dtype/index metadata, so we hand-roll those.
  → `types.MethodType` (receiver + `__func__`) → `types.FunctionType` (code object **plus the state bound alongside it**: captured free variables paired with `co_freevars`, then `__defaults__` (as a tuple) and `__kwdefaults__` (as a mapping), each behind a section marker.
  Functions out of one factory share a code object, so a code-only digest could not tell `make(1)` from `make(2)`, nor `lambda x, n=1` from `lambda x, n=2`.
  A function with neither captures nor defaults still digests exactly as its code object, so nothing else changed digest.
  Cycles — a recursive inner function closes over itself, or a function is reachable from its own defaults — fold in a marker naming how far back up the walk the target sits, guarded by a per-thread dict of the functions currently being walked and their depths (relative, so a cycle digests the same wherever it is met — a constant marker would collide `a -> b -> a` with `c -> d -> d`);
  an empty cell folds in its own marker;
  the compiler-inserted `__class__` cell (every method mentioning `super()` has one) is folded in via `digest_class` as `module.QualName` rather than as a value, since user classes are `Indigestible` and digesting it would refuse every such method;
  any other indigestible capture or default raises.
  `__digest__` is honoured **per instance** here — all functions share one type, so a class-level lookup could never distinguish them — which is the escape hatch for a closure over something unhashable and how `make_wrapper` gives each wrapper the digest of the function it wraps) / `CodeType` → `datetime.{timezone,timedelta,datetime,date,time}` → `staticmethod` / `classmethod` / `property` → built-in `type` objects (qualified-name digest of `int`/`str`/… via the shared `digest_class`, restricted to `value.__module__ == 'builtins'`;
  user-defined classes raise `Indigestible` as *values*) → `dataclasses` and `attrs` instances (flat field-dict, so the two layouts hash identically;
  both arms guard `not isinstance(value, type)` so a dataclass *class* falls through to `Indigestible` rather than crashing on missing field defaults) → `types.ModuleType` (digests `__all__` if defined else `dir()`) → `Mapping` → `Iterable`.
  User types opt in by defining `__digest__` on the class — checked before the built-in cases so dict/list subclasses can override (negative answers are cached in `_TYPES_WITHOUT_DIGEST` so the hot path is one set lookup).
  The `Hook` registry (`add_hook`) and entry-point plugin loading (`[project.entry-points."fleche"]`, key `digest`) are for *third-party* types you can't modify;
  the hot path skips `get_hooks()` entirely when both registries are empty.
  `digest()` is the single public entry point — it calls `load_entry_points()` on an `Indigestible` and retries once before re-raising;
  bound methods are their own arm (`types.MethodType`: receiver + underlying function, so `obj1.m` and `obj2.m` differ;
  a class receiver is named via `digest_class`), so there is no second entry point — `call._code_digest` reduces a bound method to `__func__` (the receiver already arrives as a call argument) and goes through `digest`;
  `digest_class(cls)` names a class `module.QualName` and is shared by the built-in-`type` arm and the `__class__` cell.
  `_new_hash(salt)` is the one place a salted running hash is started.
  NaN floats are packed via `struct.pack` (sign-preserving) instead of going through `hash()`;
  complex NaNs use `<dd`.
- `_attrs.py` — Internal `is_attrs_instance` / `field_items` helpers gating optional `attrs` support;
  safe to import without `attrs` installed.
- `call.py` — `Call` dataclass (`from_call`, `to_lookup_key`, `.stash(values)→DigestedCall` writes args+result to value storage / `.digest()→DigestedCall` digests without saving);
  `DigestedCall` (storage representation: arguments and result are `Digest` keys;
  `result` is `Digest | None` — `None` marks a record whose result is still pending, i.e. an admission by `Cache.prepare` that has not yet been committed;
  `.fetch(cache)→LazyCall`);
  `LazyCall` (private `_arguments`/`_result`, deferred deser via `_cache`;
  `LazyArguments` Mapping resolves digests on access;
  `.fetch()→Call` materialises every value into a plain `Call`;
  `.detach()→DigestedCall` is the cache-stripping inverse of `DigestedCall.fetch`, used by `remote._strip_cache` to put a call back on the wire);
  `PreparedCall` (the two-phase-save middle state: a `DigestedCall` whose arguments were stashed by `Cache.prepare` and whose result is still awaited;
  `.commit(result, metadata=None)` calls the injected cache's `save(self)` to file the record,
  `.abandon()` releases without filing (the argument values become content-addressed orphans for the next `gc` sweep — issue #826 tracks fixing this),
  `.resolve(values)` is the shared save-side ending that stores the pending result into a value storage and returns the final `DigestedCall`.
  Doubles as a sync context manager (leaving the block without commit auto-abandons).
  Not hashable and never crosses the wire — `SshCache.save` unpacks it into a `save_value` + `save(digested)` pair.);
  `QueryCall` (wildcard match via `matches`, built via `partial=True` binding;
  ignores the profile's `code_digest` by default — set explicitly to filter on it;
  no `__digest__`);
  `bind()` wrapper over `inspect.Signature.bind[_partial]`;
  `AnyCall = Call | LazyCall`.
  `Call`, `DigestedCall`, and `LazyCall` digest identically when their fields agree.
  `Ignored`/`Required` marker classes live here (re-exported via `wrapper.py` for the public API).
  All static per-function metadata (signature, qualname, module, version, `code_digest`, ignored/required arg sets) is consolidated in the frozen `FunctionProfile` dataclass;
  `FunctionProfile.of(func)` performs every introspection step;
  `_profile` is a single `lru_cache(maxsize=1000)` backing `_get_profile()`, which falls back to `_profile.__wrapped__` for unhashable callables (the `TypeError` from `lru_cache`).
- `caches.py` — `BaseCache`, `Cache`, `CacheStack`, `CachePool`, `ReadOnlyCache`, `FilteredCache`, `RefreshingCache`, `SizeLimitedMixin`/`SizeLimitedCache`;
  `Rejected` exception.
  **Two-phase save protocol** — every `BaseCache` exposes `prepare(call: Call) → PreparedCall` alongside `save(call: PreparedCall | Call) → str`;
  `save` still accepts a plain `Call` for the one-shot path (values stashed on the spot, e.g. `Cache.redigest` re-saving already-fetched calls), while `prepare` seals the record's lookup key *before* the function body runs so an argument-mutating body cannot leak its post-mutation state into the recorded key.
  Overrides: `Cache.prepare` returns `PreparedCall(digested=call.stash(self.values), cache=self)` — the values ride into `self.values` immediately, then `Cache.save` on a `PreparedCall` calls `.resolve(self.values)` to store the pending result (never re-stashes the arguments);
  `CacheStack.prepare` delegates to `stack[0].prepare` (writes always land on `stack[0]`);
  `CacheWrapper.prepare` delegates to the inner cache and rebinds the resulting `PreparedCall.cache = self` (so wrapper policy — read-only, filtering, size limits — still governs the eventual commit);
  `ReadOnlyMixin.prepare` returns a digest-only admission (nothing stashed) so the body runs uncached and the commit `Rejected`s at `save`;
  the base `BaseCache.prepare` is the same digest-only admission for caches that lack their own value storage.
  Wrapper-cache scaffolding: `CacheWrapper` (forwarding base — every `BaseCache` method delegates to `self.cache`) plus behaviour mixins `ReadOnlyMixin` and `FilteringMixin` (filters `load`/`_query` by a predicate);
  `ReadOnlyCache(ReadOnlyMixin, CacheWrapper)`,
  `FilteredCache(ReadOnlyMixin, FilteringMixin)`,
  `RefreshingCache(CacheWrapper)` overriding `load`/`contains` to always miss — extend by mixing these the same way.
  **`ReadOnlyMixin`** is a **field-free, base-free** behaviour mixin (turns `save`/`evict` into `Rejected`;
  never touches `self.cache`) so it composes onto *either* a single-cache wrapper *or* the multi-cache `CachePool` — place it **first** in the bases so its `save`/`evict` win over the forwarding/aggregating impl.
  It is also the marker `remote._is_read_only` keys on (`isinstance(cache, ReadOnlyMixin)`), so every cache mixing it in — including `CachePool` — is recognised as read-only by the SSH layer.
  **Multi-cache fan-out** is shared via `_MultiCache(BaseCache)` — an abstract base exposing the members through an abstract `_members` property and owning the read fan-out (`contains`=any, `load_value`/`expand` via the three helpers, `_shrink` per-member batched loop, `_query` union-dedupe) plus the helpers `_first_hit`/`_collect`/`_foreach`.
  `CacheStack(PerKeyLockMixin, _MultiCache)` and `CachePool(ReadOnlyMixin, _MultiCache)` both subclass it.
  `CachePool(ReadOnlyMixin, _MultiCache)` is a **read-only, unordered collection** (`caches: tuple[BaseCache, ...]`): read-only-ness is inherited from `ReadOnlyMixin` (so `save`/`evict` raise `Rejected` *and* the SSH layer's `_is_read_only` recognises it — not hand-rolled),
  `load`/`load_value` are first-hit-wins, and — unlike `CacheStack` — `load` never back-fills, so members are never mutated by a read.
  Member order only decides which copy a `load` collision returns.
  Built via `cache_from_config` from a dict with a `pool` key (array-of-tables), round-tripped by `cache_to_config` to `{"pool": [...]}`.
  On `BaseCache`: `transfer(other, pop=False, overwrite=False)` is a one-liner over `self.query().transfer(...)` (the `_cache is source` invariant is pinned in `tests/regression/test_issue_592.py`;
  the conflict-skip-unless-`overwrite` policy and "only evict on `pop` when actually transferred" live on `QueryIterator.transfer`, which warns on the `fleche.query` logger),
  `_transfer_one(c, *, overwrite=False) → bool` (the atomic check-then-save behind `transfer`: holds `self._operation_context(key)` across `contains`→`save`, closing the check-then-save TOCTOU (#452);
  returns `True` if written, `False` if skipped on conflict, so `QueryIterator.transfer` can warn on its own `fleche.query` logger;
  fetches the call only on the write path so a skip pays no deser;
  never `shrink`s — internal callers must not, it's a user-only convenience, so the skip warning logs the full lookup key).
  The lock is honest for wrapper/stack targets because `CacheWrapper` **forwards** `_operation_context` to its wrapped cache and `CacheStack` overrides it to lock `stack[0]` (the write target) with the real intent while entering every other member with the no-op `Intent.READ` — so wrapper/stack targets lock their *real* inner `Cache` instead of inheriting the no-op cache-layer context, and `contains`/`save` still route through `self` so read-only/filtering overrides are preserved.
  `readonly`, `push`, `filter`, `table`, `query(template_or_None, **kwargs)` (template *or* kwargs, not both;
  the iterator wraps `_query` in a try/except so an `Indigestible` template arg logs a warning and yields nothing rather than propagating).
  On `Cache` only: `redigest` (re-saves any call whose `to_lookup_key()` no longer matches its stored key — unchanged ones are left alone, unlike `CallStorage.transform`;
  a failure mid-loop leaves already-processed calls migrated, with no rollback — pinned as intended in `test_redigest.py`);
  `gc` (mark-and-sweep over call records, transitively following destructured sub-references via `DestructuringMixin.child_digests` when the value storage satisfies the `HasChildDigests` protocol, then evicts every unreachable `values` key;
  call records untouched).
  `Cache.contains` short-circuits to `self.calls.contains(key)` (no value deser);
  `BaseCache.contains` falls back to `load`+`KeyError`.
  **Shrink** is a Template Method: `BaseCache.shrink(*keys) → Digest | tuple[Digest, ...]` is concrete on the base and owns the empty-keys guard plus the single/tuple unwrap;
  subclasses implement only the abstract `_shrink(*keys) → tuple[Digest, ...]`.
  The empty-keys guard and unwrap are shared with `KeyManagement.shrink` (storage layer) via the module-level `storage.base._apply_shrink(shrink_many, keys)` helper — each layer keeps its own `shrink()` docstring and its own `_shrink` batching strategy;
  only the boilerplate around calling it is deduplicated.
  `Cache._shrink` partitions keys by which sub-storage `contains` each (call vs value) and hands each partition to that sub-storage's batched `shrink` once — no `_combine_shrink` (mixing call+value keys in one call is undefined).
  `CacheStack._shrink` runs a per-layer batched loop and aggregates per key via `_combine_shrink` (longest/safest prefix).
  `CacheWrapper._shrink` forwards to `self.cache._shrink` (in-process layers call the inner `_shrink` directly, since it always returns a tuple;
  only `SshCache._shrink` goes through the remote's public `shrink()` and re-wraps the single-key result).
  `Cache.expand` aggregates `(self.calls, self.values)` via `storage.base._resolve_prefix(key, results, dedupe=True)` (raises `AmbiguousDigestError` when sub-storages disagree);
  `CacheStack.expand` aggregates over the stack the same way.
  `CacheStack` saves to `stack[0]` (the codebase calls this the "lowest";
  `stack[i>0]` are "higher");
  `load`/`_query` iterate `stack[0]→stack[-1]`, `load` back-fills any hit on `stack[i>0]` into `stack[0]`, `_query` dedupes by `to_lookup_key()`.
  `push(c)` inserts at `stack[0]`.
  Cannot nest (`__post_init__` rejects `CacheStack` members).
  Fan-out across the stack is consolidated in three private helpers — `_first_hit` (first-non-`KeyError` wins;
  used by `load_value`), `_collect` (gather non-misses;
  used by `expand`;
  `_shrink` runs its own per-layer batched loop), `_foreach` (best-effort over every cache, swallows `(Rejected, KeyError)`;
  used by `evict`) — new multi-cache methods should be expressed as a one-liner over whichever helper fits rather than re-writing the traversal.
  `SizeLimitedMixin.__post_init__` populates its `_keys` set by running a full wildcard query — opening a `SizeLimitedCache` over a large existing cache pays O(N) up front (#920).
  Its `_lock` is a `_PicklableRLock` so `SizeLimitedCache` pickles.
  Default eviction is uniform random via `_pick_eviction_target(list[str])`;
  override that single method to plug in LRU/LFU/etc.
- `state.py` — `cache()`, `meta()`, `tags()`, `project()`;
  `_lazy_default(var, key, loader)` — the shared try-the-`ContextVar`, else-memoise-`loader()`-into-`_DEFAULTS` fallback behind `get_cache()`/`get_metadata()`;
  `_StickyContext` (backport of Py3.14 Token CM) plus the two shared primitives that drive it — `_sticky_set(var, value)` (set immediately, return a `_StickyContext` that restores on `__exit__` and stays active when discarded — used by `cache()` and `meta()`) and `_hard_set(pairs)` (@contextmanager that sets every `(var, value)` on entry and resets them in *reverse order* on exit whether by return or exception — used by `BoundWrapper.__call__` so metadata resets before cache);
  `BoundWrapper` (frozen dataclass that pins the active cache + metadata tuple at `.bind()` time and re-installs them around every call — used for shipping fleche calls through pickle / executors).
- `query.py` — `QueryIterator` over `LazyCall`.
  Chainable (return new `QueryIterator`s): `take/skip/filter/unique/sorted`.
  Terminal: `only/any/count/empty/latest/oldest/evict` (consume);
  `transfer(target, pop=False, overwrite=False)` replays the filtered subset into another cache (mirrors `BaseCache.transfer` but post-filter;
  per key it delegates the atomic check-then-save to `target._transfer_one(c, overwrite=...)` — the target holds its own per-key context across `contains`→`save`, closing the #452 TOCTOU for plain *and* wrapper/stack targets, pinned in `tests/regression/test_issue_452.py`;
  `_transfer_one` returns a bool (`False` on conflict-skip) so this layer logs the skip warning (with the full lookup key — internal callers never `shrink`) on the `fleche.query` logger, and only public cache methods are touched here — no private-hook reach-in);
  `groupby` → `dict[Any, QueryIterator]`;
  `table` → pandas DataFrame;
  `results()` → plain `Iterator[Any]`.
  `QueryIterator.calls` is a *factory* (zero-arg callable returning a fresh iterable) so the iterator is re-iterable — every `for` / `list()` / terminal call starts a new traversal and reflects current cache state.
  `sorted` re-sorts on each iteration.
  `QueryIterator` carries an optional `cache` field set by `BaseCache.query()` (falling back to `LazyCall._cache` for hand-built iterators) and propagated through chainable methods.
  `.table()` indexes by the lookup-key digest, **shrunk to the shortest unambiguous prefix by default** (`shrink_keys=True`, via that `cache`;
  pass `shrink_keys=False` to keep full 64-char digests on large caches);
  it also auto-converts `timestart`/`timestop` to local tz;
  argument names that clash with built-in/metadata columns are prefixed `a_`.
  `latest`/`oldest` consult `metadata["runtime"]["timestop"]` only;
  an empty iterator raises `IndexError`, and matching calls of which *none* carries that key raise `ValueError` naming the fix (`meta=['Runtime']`) instead of returning an arbitrary pick — in the mixed case undated calls still lose to any real timestamp.
  `sorted`/`unique`/`groupby` accept either a callable or an argument-name string (resolved via `_resolve_key` to `c.arguments[name]`).
- `metadata.py` — `MetaData` ABC: `keys` is a **concrete** `@property` returning `self._keys` — subclasses with a static schema just declare `_keys: ClassVar[dict[str, type]]` once (default `{}` on the ABC), subclasses whose schema depends on instance state override the `keys` property directly.
  Drift guard: `tests/unit/metadata/test_metadata.py::test_builtin_metadata_pre_post_keys_match_schema` asserts each static built-in's `pre`/`post` output keys equal `_keys`.
  `name` is a plain class attribute, set automatically by the `@configurable` decorator (`cls.name = cls.__name__.lower()` for the per-instance namespace, plus registers the class in module-level `CONFIGURABLE: dict[str, type[MetaData]]` keyed by **PascalCase `cls.__name__`** — so TOML uses the class name verbatim).
  `pre(call)` / `post(pre, call)` are concrete and default to `{}`;
  returns must be JSON-serialisable (`JSONValue` alias).
  Built-ins decorated `@configurable` (selectable from TOML `metadata = [...]`): `Runtime` (timestart/timestop/walltime/cputime/systime, name=`"runtime"`),
  `Environment` (hostname/username/cwd/fleche_version/python_version captured in `pre`, name=`"environment"`;
  `fleche_version` is `"unknown"` in an editable checkout without a built `_version.py`), `Git` (root/commit/branch/dirty via `git` subprocess in `pre`;
  all `None` when outside a repo or `git` is missing, name=`"git"`).
  `Runtime`'s `cputime`/`systime` live on `Runtime` rather than a separate built-in, keeping "how long and how much" in one namespace (`peak_rss` is deliberately absent — a true per-call peak isn't recoverable without sampling during execution);
  they sum `RUSAGE_SELF + RUSAGE_CHILDREN` via the stdlib `resource` module, so subprocess cost (e.g. shelling out to `git`) is counted;
  `pre` snapshots the CPU baseline under the same key names `post` reports, so `post`'s `|=` union overwrites the baseline with the delta;
  both are omitted entirely (not present as `None`) on platforms without `resource` (Windows), while `timestart`/`timestop`/`walltime` are unaffected since they don't depend on it.
  `Tags` is **not** decorated because it needs constructor args (`tags: dict`);
  it sets `name="tags"` manually, overrides `keys` (schema derived from `self.tags`), and stays excluded from `CONFIGURABLE`.
  `config.load_default_metadata()` looks the requested string up in `CONFIGURABLE` and raises on unknown/non-configurable names.
- `config.py` — TOML loader (`load_cache_config`, `load_default_metadata`);
  `storage_from_config`/`storage_to_config` (thin wrappers over the `storage.base` registry — `get_storage_constructor(type, kind)` one way, the instance's own hand-written `to_config()` the other;
  see the `base.py` bullet under Storage layout), `cache_from_config`/`cache_to_config` (round-trippable);
  `_live_caches` (`dict[str | None, …]`) interns named caches plus the default under key `None`.
  `cache_from_config` dispatches `type="ssh"` → `SshCache` before its read_only/max_size/plain branches.
  `load_cache_config` routes through `cache_from_config`, so TOML honours `max_size`, `read_only`, and array-of-tables list-stack configs identically to the programmatic API.
  `_default_memory_cache(name, reason)` is the single fall-back/intern path for the "no config" / "not found" cases.
  `_load_config` runs `_rebase_config` on each discovered file before the merge, rebasing relative `root`/`url` values onto that file's directory (absolute, `~`-prefixed, `sqlite:///:memory:`, non-sqlite dialect URLs, `[default].root = true`, and ssh `workdir` are left alone);
  `root`/`url` passed straight to `cache_from_config`/`storage_from_config` still resolve against the CWD.
  See module docstring for full type reference and TOML examples.
- `security.py` — `SignedBytes` HMAC-SHA256 wrapper (hex-encoded so it never contains pickle STOP, which is how `loads` finds the signature boundary);
  `SignatureError`;
  `normalize_secret_key`/`get_secret_key`;
  `FLECHE_SECRET_KEY` env var (colon-separated hex) / `secret_key` config key
- `executor.py` — `wrap_executor(executor)` monkey-patches `.submit`: cached fleche calls skip the executor and return a pre-completed `Future`;
  **every** other callable is `BoundWrapper.bind`'d before submit so any nested fleche calls in a plain outer function still see the active cache/metadata (pinned in `tests/regression/test_issue_691.py`) — a callable already a `BoundWrapper` submits as-is instead of double-binding.
  Splits off executor-reserved kw-only params (e.g. `resources=`) from payload kwargs.
  Idempotent (`submit._fleche_wrapped`).
- `__main__.py` — `python -m fleche <command> …` argparse dispatcher.
  The only subcommand is `remote --serve [--cache NAME]`, which imports `remote._run_server` and runs the RPC server `SshCache` connects to.
  Deliberately routed here rather than `python -m fleche.remote` so `runpy` doesn't double-import `remote.py` (once as submodule, once as `__main__`) with duplicate class/exception objects.
  Extend by adding a parser branch in `_build_parser` and a dispatch arm in `_main`.
- `remote.py` — `SshCache(BaseCache)` (frozen dataclass): forwards every cache op to a `python -m fleche remote --serve` subprocess (note the **space** — the CLI is an argparse dispatcher in `__main__.py`) over one persistent SSH subprocess carrying length-prefixed **cloudpickle** RPC frames — one round-trip per method.
  `load`/`_query` rebind returned `DigestedCall`s back to `self`.
  Lazy connect + an `info` handshake that warns on fleche/cloudpickle version skew and caches a `read_only` flag to short-circuit `save`/`evict`.
  `_server_info` runs `cache_to_config(cache)` through `_redact_config` before serialising: `secret_key` values become `<redacted>` and any `url` values have their password component masked via `_redact_url_password`, so HMAC signing keys and SQL DB passwords never ride in `info()`'s return value — which is ordinary user-visible data a caller might print or log (regression-pinned in `tests/unit/test_remote.py`, including the list-walk / nested-URL path a `CacheStack` of SQL-backed caches takes;
  the client's DEBUG RPC tracing is *not* the exposure path — `rpc →` logs method + args, `rpc ←` only method + an ok/err tag, never response payloads).
  `info()` defaults to `refresh=True` (a fresh RPC per call;
  pass `refresh=False` to reuse the cached copy), while the `read_only` property reads through the cached info dict, so only its first access pays a round-trip.
  Fields: `host`, `cache_name`, `python`, `ssh_options`, `setup_commands`, `workdir`.
  `__all__`: `RemoteConnectionError`, `SshCache`, `serve`.
  Requires the `ssh` extra (cloudpickle).
  Server-side dispatch is the `_REMOTE_METHODS` registry (each entry a `call(cache, args)` plus a `void` flag — `evict`'s return value is not part of the wire contract);
  the client mirrors it with `_CLIENT_METHODS`, driving a `_rpc(name, *args)` dispatcher (`unwrap` per method, plus `write`/`reject_message` so `save`/`evict` raise `Rejected` locally on a read-only remote without an RPC);
  #737 proposes merging the two inventories.
  **Two-phase save on the wire:** `SshCache.prepare` is one RPC that ships the whole `Call` to the server, which runs `cache.prepare(call)` and ships back only the sealed `DigestedCall` — the `PreparedCall` itself never crosses the wire (the server drops its side and the client wraps the reply in a fresh `PreparedCall(cache=self)`).
  Read-only remotes short-circuit locally to the base digest-only admission before dispatching, saving the round-trip.
  `SshCache.save(prepared)` is two RPCs: `save_value(result)` stores the pending result via the `_save_value` server helper (routed through `cache.prepare(...).abandon()` so wrappers and stacks target the same storage their real saves use — `None` rides as an argument since storing `None` cannot fail, everything else rides in `result` position for its strict save semantics), then `save(digested)` files the sealed record.
  A failure between the two trips leaves the value as a content-addressed orphan for `gc` — same as any abandoned local call.
  Values still travel by cloudpickle, so a `Path` argument ships its path *string*, not its content — paths over `SshCache` are unsupported (#829 tracks client-side blob conversion;
  the `temppath` branch carries a `RemotePathUnsupported` refusal that is not on `main`).

**Storage layout (`storage/`):**
- `base.py` — `OperationContext(ABC)` (the root of both the storage and cache hierarchies) exposes the `_operation_context(key, *, intent=Intent.WRITE)` context-manager hook — chain via `super()._operation_context(key, intent=intent)`;
  the `intent: Intent` kw-only param is a `StrEnum` with `WRITE` (the default — takes the exclusive lock) and `READ` (a **no-op** today: the lock mixins short-circuit it and acquire nothing;
  reserved for a future reader-writer/shared lock, so it must never guard a read-modify-write).
  `CacheStack._operation_context` enters its non-`stack[0]` members with `READ`, so a transfer into a stack only really locks `stack[0]` where the write lands.
  `KeyManagement(OperationContext)` adds the abstract `list`/`_evict`/`_contains` plus concrete `evict`/`contains`/`expand`/`shrink`/`_normalize_key` (`expand` raises `KeyError` for prefixes shorter than 4 chars;
  it owns the operation context, the length guards and the `_resolve_prefix` call, so subclasses override only the `_prefix_candidates(prefix)` hook — default filters `list()` Python-side,
  `Sql` pushes down `LIKE … LIMIT 2`).
  `StorageBackend(KeyManagement)` adds `put`/`get`.
  Domain ABCs `ValueStorage`, `CallStorage` (the latter also exposes `transform(func=None)` — re-saves every entry through *func*;
  entries whose `to_lookup_key()` changes are saved under the new key and the old one is evicted, unchanged ones are re-saved idempotently.
  `func=None` applies the identity, which is the form to use after a hash-function change.
  The analogous `Cache.redigest` does its own loop because it must update `values` too).
  **Bridge mixins** `ValueMixin`/`CallMixin` implement `save`/`load`[/`query`] on top of `put`/`get`.
  Also: `SaveError`, `AmbiguousDigestError`, `_resolve_prefix` (used by both base and `Sql`).
  **Config dispatch** lives here too: `register_storage(name, kind, *, factory=None)` is a class decorator each concrete backend applies to itself where it is defined — it fills the `(name, kind) → constructor` table that `get_storage_constructor` (and hence `config.storage_from_config`) reads, and records the class in `_STORAGE_CLASSES`.
  Adding a backend means one decorator, not four edits in `config.py`.
  Pass `factory=` when construction needs an entry point other than `cls(**kwargs)` (`MemoryBackend.from_config` seeds the empty store the config omits;
  `PickleFileBackend.with_pickle`/`with_dill`/`with_cloudpickle` bind the serializer);
  one class may register under several names (only the pickle family does).
  The reverse direction is **not** inherited: there is deliberately no `StorageBackend.to_config`, and each concrete class writes its own dict out by hand,
  `type` key included — `ValuePickleFile`/`CallPickleFile` derive theirs from `self.serializer` since one class serves three names.
  `config.storage_to_config` guards the call with `is_registered_storage(type(s))` (an exact-class check), so a user subclass of `ValueMemory` raises rather than silently serialising as `{"type": "memory"}` and round-tripping back as the parent.
  `OperationContext`, `KeyManagement`, `Intent`, `StorageBackend`, `ValueStorage`/`ValueMixin`, `CallStorage`/`CallMixin` are all re-exported from `fleche.storage`.
- `file.py` — `FileStorage` base for disk-backed backends (also re-exported from `fleche.storage` for subclassing).
  Lock-free (since 0.22.0;
  releases through 0.21.2 lock per key): `put` routes `_to_file` through the module-level `_atomic_write` helper (write to a dot-prefixed `uuid4` temp sibling, `Path.replace` into place — readers see the old or new complete file, never a torn one;
  `_to_file` must therefore write a complete file at whatever path it is given), and `get` reads directly.
  `lock_timeout` lives only on `BagOfHoldingH5FileBackend`, the one backend that still locks;
  `config.storage_from_config` drops the key from pickle-family configs with a `FutureWarning` so older configs keep loading (#893 argues against deprecating `lock_timeout` config-wide — the multi-bag backend needs the knob;
  check it before touching `lock_timeout`).
  `list()` filters `*.lock` (litter from pre-0.22 releases — filelock never unlinks — and the locking subclass's live locks) and dot-files (in-flight temps);
  fleche deliberately does not sweep legacy litter — `find <root> -name '*.lock' -delete` once no pre-0.22 fleche uses the directory.
  `root` is resolved (`expanduser`+`absolute`+`resolve`) in `__post_init__`.
  Subclasses implement `_to_file`/`_from_file`;
  compression and signing live in `pickle_file.py`, not here.
- `memory.py`,
  `void.py`,
  `pickle_file.py` (+`PickleFileBackend.with_pickle`/`with_cloudpickle`/`with_dill`, each a thin shim over `with_serializer(name, ...)`, which sets the `serializer: str` field and looks up its `(dumps, loads)` pair from a `_SERIALIZERS` name→loader registry filled by `register_serializer(name, loader)` — `loader` is a zero-arg callable so an optional serializer's `ImportAlarm`-gated import only fires when that name is actually selected, not at module import time;
  `dumps`/`loads` are `init=False` dataclass fields set in `__post_init__`, not constructor args, so `to_config` reads the servable name straight off `self.serializer`;
  `compress_all`/`decompress_all` migration helpers;
  gzip auto-detected by `\x1f\x8b` magic on read),
  `bagofholding_file.py` (keeps cross-process `filelock` locking for **multi-bag mode only** — those files are shared between keys and mutated in place, so atomic rename can't make them safe: `put`/`get`/`_lock_path` overrides plus `_file_read_lock_with_fallback` — on read-lock timeout logs a warning and reads anyway, a torn/missing file then surfaces as `KeyError` — live here now, locking `{prefix}.h5.lock` per bag, unlinked with the emptied bag by `_evict`;
  per-key mode `prefix_length=0` inherits the base's lock-free atomic-rename `put`/`get` (H5Bag writes the temp sibling in full) and litters nothing;
  +`rebag(version_validator="none")` re-saves every bag through a chosen validator, useful when older bags would fail strict version checks;
  `_from_file` opens the bag with `H5Bag(path, _skip_load=True).load(...)` so the file is opened exactly once per read;
  optional `prefix_length: int | None = 2` on `BagOfHoldingH5FileBackend` multiplexes keys sharing the first `prefix_length` chars into one `root/{prefix}.h5` file as sibling groups named by the full key, via bagofholding 0.1.12's `file.h5/group` path addressing — single-level, fixed-length split only;
  the default `2` multi-bags into up to 256 files,
  `prefix_length=0` restores the one-file-per-key layout, and `prefix_length=None` infers the length from the files already in `root` (empty root → the default `2`).
  Layout maintenance: `refix(n)` copies every entry into a new `prefix_length` layout and returns the re-fixed storage, leaving the receiver invariant (target must be an explicit int, `0` = per-key;
  fails fast on unreadable entries;
  resumable — entries already in the target layout are skipped),
  `__post_init__` raises `ValueError` when the configured `prefix_length` doesn't match the layout of files already in `root` (skippable via the init-only `check_consistency=False`, which requires an explicit `prefix_length` and makes the instance blind to all other layouts' files), and the `consolidate(root, n)` classmethod repairs a mixed-layout root by refixing every other prefix length it finds to `n`),
  `sql.py` — concrete backends (each exposes `Value*` and/or `Call*` classes;
  `sql.py` only has `Sql` for calls).
  `MemoryBackend.put`/`get` deep-copy values, so mutating a stored object after retrieval does not affect later reads.
  `Sql.query` always pushes name/module/version/code_digest/result and argument filters down to SQL (arguments are compared as `digest(value)` strings via `JOIN`s on the `arguments` table).
  Metadata filters are pushed down only when *every* filter value is a simple scalar (`str`/`bool`/`int`/`float`) via JSON-extract `as_*` casts;
  any `None` or complex (e.g. list) value disables metadata pushdown only — name/argument filters still apply at SQL level — and the post-load `meta_matches` check runs on every yielded result regardless.
  `Sql` does not inherit from `CallMixin` — it implements `CallStorage.save` directly, folding the existing-row check into a private `_persist_call` helper that runs in one transaction (no separate `contains`+`evict` round-trip), with `PerKeyLockMixin` keeping concurrent saves serialised (see `regression/test_sql_concurrent_save.py`).
  The companion private helper `_fetch_call` materialises a `DigestedCall` from a row plus its argument/metadata child rows;
  `Sql` does not expose any `put`/`get` methods (it isn't a `StorageBackend` subclass).
  `_coerce_sqlite_url` accepts a bare path (treated as sqlite, parent dir auto-created), a `sqlite:` URL, or any other SQLAlchemy URL (e.g. `postgresql://`, `mysql+pymysql://`) verbatim.
  `:memory:` is special-cased.
  SQLite-only PRAGMAs are gated on `dialect.name == "sqlite"`: `foreign_keys=ON` runs on every connect (per-connection setting),
  `journal_mode` is set **once** at engine creation because it persists in the db file (`WAL` by default, `DELETE` when `_is_network_filesystem(db_path)` matches — Linux-only, parses `/proc/mounts` with a longest-mount-prefix / last-wins tie-break so an autofs stub followed by the real `nfs` mount at the same point resolves to `nfs`;
  best-effort — non-Linux or an unreadable `/proc/mounts` reports "not network";
  network types are `nfs`/`nfs4`/`cifs`/`smb*`/`ceph*`/`glusterfs`/`9p`/`lustre`/`gpfs`/`panfs`/`afs`/`afpfs`;
  a warning is logged when WAL is skipped).
  `:memory:` skips `journal_mode` entirely.
  The schema is three tables: `calls`, `arguments` (one row per arg, `UNIQUE(call_key, name)`, ordered by `position`), `metadata` (one JSON blob per metadata namespace, `UNIQUE(call_key, name)`).
  `arguments.call_key`/`metadata.call_key` are FKs with `ondelete="CASCADE"`, so `_evict` is a single `session.execute(delete(CallModel).where(...))` (SQLAlchemy DSL, no raw SQL or ORM materialisation) and lets the DB clean up child rows (SQLite needs the `foreign_keys=ON` PRAGMA the dialect listener installs;
  Postgres/MySQL enforce FK cascades natively).
  MySQL/MariaDB needs explicit `VARCHAR(255)` for indexable name columns;
  other dialects get unbounded `TEXT` via `String().with_variant(...)`.
  `Sql` also accepts `check_same_thread=False` only for sqlite drivers (skipped for Postgres/MySQL where the flag would raise at connect).
- `destructuring.py` — `DestructuringMixin` for recursive value splitting + `Digested` ABC with markers `DigestedIterable` (lists/tuples),
  `DigestedDict`, and `DigestedFields` (shared base reconstructing instances via `object.__new__` + `__setattr__`, bypassing `__init__`/`__post_init__`, so `init=False`/`InitVar`/frozen/slots fields round-trip) with two concrete subclasses `DigestedDataclass` (stdlib dataclasses) and `DigestedAttrs` (`attrs`-decorated classes).
  All preserve digest equivalence via `__digest__`.
  Subclassing contract: `sunder` is a *concrete template method* — a new `Digested` subclass implements `underlying`,
  `mend`, and the three abstract classmethod hooks `_slots(value)` (enumerate `(label, child)` pairs to recurse into, or `None` to opt out),
  `_rebuild_plain`, and `_rebuild_digest`;
  neither `DigestedIterable` nor `DigestedDict` overrides `sunder` itself, and a `DigestedFields`-style subclass implements only the static `_field_items`.
  `DestructuringMixin` is a `ValueStorage` subclass — operates at the `save`/`load` layer, not `put`/`get`;
  compose **above** `ValueMixin` in the MRO.
  `remaining_depth` (default `1`) controls how deep structures are split across keys.
  `child_digests(key)→set[Digest]` returns the immediate digest references of a stored entry (raw, pre-`mend`);
  `count_reuses()` tallies how often each key is referenced as a sub-component (useful for GC-style audits).
  The `HasChildDigests` `runtime_checkable` Protocol declares the `child_digests` shape so `Cache.gc()` can opt-in to transitive walks via plain `isinstance` — any future value storage that exposes `child_digests` satisfies it without explicit registration.
  NamedTuples are deliberately **not** destructured (`_is_trojan_tuple` guard).
  `register_destructurer(pred, fn)` (re-exported from `fleche.storage`) appends a new entry to the module-level `_DESTRUCTURERS` list — first match wins, so registering a handler for a brand-new container type is safe;
  ordering matters if you want to override list/dict/dataclass/attrs.
- `thread_safe.py` — `SerializingMixin(OperationContext)` (single `_PicklableRLock`), `PerKeyLockMixin(OperationContext)` (striped locks via a module-level `_per_instance_locks: WeakKeyDictionary`;
  per-instance `WeakValueDictionary[key, RLock]` — so the storage instance must be **hashable**, which all the frozen-dataclass concrete classes are).
  Both mixins override `_operation_context(key, *, intent=Intent.WRITE)`;
  chain via `super()._operation_context(key, intent=intent)`.
  Both short-circuit `intent=Intent.READ` to a plain `yield` (no lock acquired) — the no-op shared-lock placeholder.
  Inheriting from `OperationContext` directly (rather than `KeyManagement`) is what lets them attach at *either* the storage layer or the cache layer — `BaseCache(OperationContext)` is the cache-layer attachment point.
  `_PicklableLock`/`_PicklableRLock` survive pickle round-trip with state not preserved — in-process only, NOT inter-process synchronisation.

**Storage class composition:** Concrete classes are `@dataclass(frozen=True)` and inherit via MRO.
Cache-layer MROs: `Cache(PerKeyLockMixin, BaseCache)`, `CacheStack(PerKeyLockMixin, _MultiCache)`, `CachePool(ReadOnlyMixin, _MultiCache)` — the lock mixin lives at both the cache and storage layers.
Thread-safety mixins are **already baked into** every stateful concrete class — do not wrap them again:
- `ValueMemory(PerKeyLockMixin, DestructuringMixin, ValueMixin, MemoryBackend)`
- `CallMemory(PerKeyLockMixin, CallMixin, MemoryBackend)`
- `ValuePickleFile(PerKeyLockMixin, DestructuringMixin, ValueMixin, PickleFileBackend)`
- `CallPickleFile(PerKeyLockMixin, CallMixin, PickleFileBackend)`
- `ValueBagOfHoldingH5File`/`CallBagOfHoldingH5File` — same pattern (PerKeyLock + [Destructuring] + …Mixin + BagOfHoldingH5FileBackend)
- `Sql(PerKeyLockMixin, CallStorage)` — bespoke;
  bypasses `StorageBackend`/`CallMixin`, implements `save`/`load`/`query` directly against SQLAlchemy (private `_persist_call`/`_fetch_call` helpers handle a single row + its child tables — no `put`/`get` method is exposed because `Sql` is not a `StorageBackend` subclass);
  `__reduce__` reconstructs from `(url, echo)`
- `ValueVoid(ValueMixin, VoidBackend)`/`CallVoid(CallMixin, VoidBackend)` — no lock mixin (trivially thread-safe;
  nothing to protect)

Each mixin/backend declares its own dataclass fields;
Python's dataclass machinery merges them into one generated `__init__` via MRO — **do not pass `init=False`** on user-facing fields.
Internal state (locks, `_keys` on `SizeLimitedMixin`, `engine`/`session`/`_local` on `Sql`) uses `field(init=False, repr=False, compare=False)` and is rebuilt in `__post_init__` via `object.__setattr__`.
Fields and config keys are independent: each concrete storage's `to_config` names its keys explicitly, so a new field only reaches a round-tripped config if you add it there — and fields that are `init=True` but not configuration (`MemoryBackend.storage`, `PickleFileBackend.dumps`/`loads`) are simply never mentioned.
`MemoryBackend`/`ValueMemory`/`CallMemory` carry an explicit `__hash__ = object.__hash__` because their `storage: dict` field is unhashable;
the file-backed classes don't need this since all of their fields hash by value.
`MemoryBackend.__init_subclass__` enforces this: every subclass that omits `__hash__ = object.__hash__` from its class body gets a `TypeError` at class-definition time.
`@dataclass(frozen=True)` regenerates `__hash__` on every subclass so the parent-class override does not carry through — without the guard the failure would surface only later, as a cryptic `TypeError: unhashable type: 'dict'` inside `PerKeyLockMixin._per_instance_locks[self]`.

---

## Architecture notes

### Core data flow

1. `@fleche()` wraps a function;
   on construction it builds a `FunctionProfile` (signature, qualname, module, version, code_digest, ignored/required arg sets — from `Ignored`/`Required` annotations and explicit `ignore=`/`require=` decorator args).
   `code_digest` comes from `call._code_digest`, which hashes the code object **and the state bound alongside it** — captured variables plus argument defaults (via `digest.digest`, after reducing a bound method to its `__func__`);
   a capture or default that cannot be digested logs a warning on `fleche.call` and falls back to the code-only digest, which re-opens the collision between functions out of one factory rather than making such a function undecoratable.
   Defaults reach the lookup key by a second route regardless of `hash_code`: `Call.from_call` calls `apply_defaults()`, so an unsupplied argument is recorded at its default value.
2. On call: `Digest` args auto-expanded → `Call.from_call()` binds via signature (applies defaults) → policy strips ignored args → `.to_lookup_key()` → `digest()` (SHA256 hex).
3. Hit → return stored result.
   Miss → run `pre` metadata hooks, execute, run `post` hooks, save `Call` + result.
   If result is a `Future`, save is attached as `add_done_callback`.
4. Active cache is a `ContextVar` — thread-safe, switchable via `with cache(my_cache):`.
5. Special cases: `None` return → not cached (warning).
   `Indigestible` arg → call runs uncached.
   Missing `Required` kwargs → call runs uncached.

### Cache key control

Decorator kwargs (`wrapper.py`): `version`,
`meta`,
`hash_version`,
`hash_module`,
`hash_code` (hashes `func.__code__`),
`require`/`ignore` (arg name lists),
`isolate` (runs in a unique tempdir under `$XDG_CACHE_HOME/fleche/cwd/`, defaulting to `~/.cache/fleche/cwd/` when the env var is unset — **not thread-safe**, uses `os.chdir`).
Per-argument markers are `Ignored[T]` / `Required[T]`.
Bump `version=` to invalidate without changing code;
`Required` kwargs not explicitly passed make a call run uncached (warning logged).

### Config

Authoritative type-string reference and a worked TOML example live in `config.py`'s module docstring.
Two API layers:

- `cache_from_config(d)` shape-dispatches in order: list → `CacheStack`;
  dict with `pool` key → `CachePool` (read-only);
  dict with `template` key → expand via `_CACHE_TEMPLATES` then recurse;
  `type="ssh"` → `SshCache`;
  dict with `max_size` → `SizeLimitedCache`;
  else plain `Cache`.
  A `read_only: true` then wraps the result in `ReadOnlyCache`.

- `template` shorthand — a dict shape that expands to a full `values`/`calls` pair via one of the entries in `config._CACHE_TEMPLATES`.
  Symmetric templates (`memory`, `pickle`, `cloudpickle`, `dill`, `bagofholding_hdf`) use the same backend for both storages;
  the filesystem ones split a required `root` into `root/values` and `root/calls`.
  The `sql` template pairs a filesystem value backend (`values=` overridable, default `bagofholding_hdf`) under `root/values` with SQL call storage (`url=` overridable, default `sqlite:///root/calls.db`).
  Cache-level modifiers (`read_only`, `max_size`) are carried through to the expanded config;
  anything the template doesn't cover (mixed backends, per-backend `compress`/`secret_key`/…) falls back to the explicit `values`/`calls` form.
  Unknown template names / missing required kwargs raise `ValueError`.
  Templates nest inside stacks/pools by dropping the `{"template": …}` dict into the list / `pool` array.

- `BaseCache.from_config(config)` is a public classmethod thin wrapper around `cache_from_config`, defined on `BaseCache` in `caches.py` with a lazy `from . import config` import (module-level import would be circular).
  The returned cache is whatever shape the config dispatches to, not necessarily `cls`;
  pass it to `cache(...)` to install it.

- `load_cache_config(name)` is the TOML loader (called lazily from `state.get_cache()`/`get_metadata()` on the first access that finds no active `ContextVar` — never at import time);
  routes through `cache_from_config`.
  `"memory"` / `"void"` are special-cased and bypass the file;
  `"default"` (and no-arg) resolves to the configured default cache, interned under `None` — `[default].cache` may be either a section name (string) or an inline cache config (any non-string goes straight to `cache_from_config`, so `cache.template = "memory"` works with no separate section).
  `metadata = [...]` accepts `"Runtime"`, `"Environment"`, and `"Git"` — `"Tags"` raises (needs arguments).

(The user-facing version of this — what to actually put in a `fleche.toml` — is in [USAGE.md](USAGE.md#config-files--where-fleche-looks-and-whats-in-them).)

### Security (optional)

Only pickle-family backends are signed.
Key rotation: first key in the list signs, all keys are tried on verify.
`SignatureError` raised by `SignedBytes.loads` is caught in `PickleFileBackend._from_file` and re-raised as `KeyError` — so tampered or wrong-key entries behave like a cache miss instead of crashing the program.

## Test layout

`tests/` has `conftest.py` (registers `tests.fixtures` as a pytest plugin),
`fixtures.py`,
`strategies.py` (hypothesis composite strategies: `dataclasses`, `namedtuples`, `calls`), and four subtrees: `unit/`,
`integration/`,
`regression/`,
`smoke/`.
Pytest config is `[tool.pytest.ini_options]` in `pyproject.toml` (registers the `smoke` marker — see below).

- `unit/` — one subdirectory per module under test: `caches/`, `call/`, `config/`, `digest/`, `fleche/`, `metadata/`, `storage/`.
  Filenames mirror the feature being tested, so a single `ls` of the relevant subdir is the fast path.
  Non-obvious landing spots worth knowing without grepping:
  - `digest/test_digest.py` (core `digest()` dispatch over built-ins),
    `digest/test_entry_points.py` (third-party hook loading),
    `digest/test_attrs.py` (attrs-class digest path),
    `digest/test_attrs_optional_dep.py` (the `fleche._attrs` shim with `attr` masked in `sys.modules` — pins the silent degradation `digest()`'s `case _ if _attrs.is_attrs_instance(value)` guard relies on;
    deliberately *not* `importorskip`-guarded, since the no-`attrs` install is the case under test), `digest/test_digest_methods.py` (`Digest.expand`/`Digest.shrink` instance helpers).
  - `call/test_code_digest.py` (`code_digest` participation in lookup key),
    `call/test_partial_binding.py` + `call/test_matches.py` (`QueryCall` semantics),
    `call/test_dehydrate.py` (`Call`↔`DigestedCall`↔`LazyCall` round-trips),
    `call/test_prepared_call.py` (the two-phase save protocol — argument-mutating body cannot leak into the recorded key;
    `PreparedCall.commit`/`.abandon` finality;
    context-manager auto-abandon on exception;
    the `save(PreparedCall)` path never re-stashes arguments;
    `Cache.redigest` still works on already-fetched calls via the plain-`Call` `save` overload).
  - `caches/test_filter.py` covers `FilteredCache` / `Cache.filter`;
    `caches/test_expand_shrink.py` covers cross-substorage digest prefix resolution;
    `caches/test_gc.py` and `caches/test_redigest.py` cover the matching `Cache` methods;
    `caches/test_lazy_call.py` covers the `LazyCall` fetch/detach paths;
    `caches/test_operation_context_cache.py` pins the `BaseCache(OperationContext)` wiring (per-key hook entry on `save`/`load`/`evict`/`contains`/`expand`/`shrink` plus the `PerKeyLockMixin` chain);
    `caches/test_cache.py::test_cache_query_logs_and_skips_calls_that_fail_to_fetch` pins the corrupt-cache silent-skip contract on `Cache._query` — an exploding `DigestedCall.fetch` in the middle of a query stream logs at ERROR on `fleche.cache` and continues rather than aborting iteration.
    Per-class files (`test_cache.py`, `test_cache_stack.py`, `test_cache_pool.py`, `test_readonly_cache.py`, `test_refreshing_cache.py`, `test_size_limited.py`) follow the class name.
  - `config/test_cache_from_config.py` + `test_cache_to_config.py` cover the config round-trip;
    `test_storage_to_config.py` is the storage-only path;
    `test_config.py` covers the TOML discovery walk.
  - `storage/test_operation_context.py` (mixin chaining),
    `storage/test_mixins.py` (`ValueMixin`/`CallMixin` contract in isolation),
    `storage/test_thread_safe.py` (the `SerializingMixin`/`PerKeyLockMixin` lock-mixin behaviour),
    `storage/test_destructuring_dataclasses.py` + `test_destructuring_storage.py` (`DestructuringMixin` + the `Digested*` markers),
    `storage/test_transform.py` (`CallStorage.transform`),
    `storage/test_secure_storage.py` (HMAC-signed pickle path),
    `storage/test_overwrite.py` (save-over-existing semantics),
    `storage/test_short_digest.py` (prefix-key resolution),
    `storage/test_optional_deps.py` (per-backend missing-dep `ImportError` surface via `patch.dict(sys.modules, {…: None})` reimport;
    complements the round-trip in `tests/smoke/test_optional_deps.py`),
    `storage/test_file_storage.py` (`FileStorage` base — `*.lock`/dot-file `list()` filtering, atomic-write `_to_file`/`_from_file` round-trip).
    SQL-specific: `test_sql_query.py` (query pushdown),
    `test_sql_pragmas.py`,
    `test_sql_url_coercion.py`,
    `test_sql_digest_types.py`,
    `test_sql_evict.py` (`Sql._evict`'s bare-`DELETE` + `ON DELETE CASCADE` contract, asserted against the `arguments`/`metadata` child tables directly).
    Per-backend basics live in `test_storage.py` + `test_{pickle_file,bagofholding_file,void}*.py`.
  - `fleche/test_fleche.py` (broad `@fleche()` smoke),
    `fleche/test_bound_wrapper.py` (cache/metadata pinning + pickle round-trip),
    `fleche/test_query_iterator.py` (chainable/terminal `QueryIterator` ops),
    `fleche/test_decorator_attributes.py` (`.call`/`.digest`/`.fleche.*` helper attachment),
    `fleche/test_type_hints.py` (`Ignored[T]`/`Required[T]` annotation parsing),
    `fleche/test_signature_binding.py` + `fleche/test_process_args.py` (ignore/require interactions),
    `fleche/test_ignore_digest.py` + `fleche/test_digest_args.py` (`Ignored`/`Digest` arg handling),
    `fleche/test_dataclass_input.py` (dataclass argument digesting),
    `fleche/test_hash_code.py` (`hash_code=True` decorator kwarg),
    `fleche/test_futures.py` (the `Future` save-via-`add_done_callback` path),
    `fleche/test_processpool.py` (executor-backed end-to-end),
    `fleche/test_rerun.py` (`.rerun` helper),
    `fleche/test_workdir.py` (`isolate=` tempdir behaviour).
  - `metadata/test_metadata.py` is the only file under `unit/metadata/` — covers the `MetaData` ABC plus the four built-ins.
  - Five files directly under `unit/` (not inside a subdir): `test_cache_sticky.py` (sticky `cache()` context semantics),
    `test_pickle.py` (pickling caches/wrappers),
    `test_main.py` (`python -m fleche` CLI dispatcher),
    `test_remote.py` (`SshCache` RPC unit tests, ssh extra),
    `test_executor.py` (`wrap_executor` unit coverage — the `submit` monkey-patch, the executor-reserved kwarg splitter, and the `BoundWrapper.bind` short-circuit).

  Optional-dep tests use `pytest.importorskip(...)` — don't wrap imports in `try/except ImportError`.
- `integration/` — `test_integration.py` (main),
  `test_notebooks.py` (exercises `notebooks/`),
  `test_parallel_execution.py`,
  `test_methods.py` (caching of bound methods / methods-as-args),
  `test_wrapper_query_integration.py`,
  `test_hash_code_integration.py`,
  `test_remote.py` (`SshCache` end-to-end, ssh extra).
- `regression/` — `test_issue_{217,297,319,352,451,452,485,578,592,691}.py`, one per issue.
  Notable: #217 — `CacheStack.load` serialises per-key back-fill so concurrent loaders don't all run the base's non-atomic save;
  #451 — `Cache.redigest` holds both old- and new-key locks across save+evict so a concurrent reader never sees the call under both keys nor neither;
  #452 — `_transfer_one` holds `self._operation_context(key)` across `contains`→`save` so concurrent transfers can't both pass the check and double-save;
  #485 — `_in_flight[key]` is populated for only the cache-write window so a second `compute()` that arrives while save is in progress hits the resolved future;
  #578 — legacy SQLite DBs that stored `version` as a raw INTEGER must not crash `Sql.load`'s `json.loads`;
  #592 — `QueryIterator._cache is source` after `BaseCache.transfer`;
  #691 — `wrap_executor.submit` binds *any* non-fleche callable so a plain outer function that calls a fleche function inside a worker still sees the active cache/metadata.
  Plus `test_sql_concurrent_save.py`,
  `test_sql_table_uniqueness.py`,
  `test_sql_non_sqlite_backends.py`,
  `test_wrap_executor_cloudpickle_lock.py` (the wrapper closure survives cloudpickle-by-value),
  `test_builtin_signature.py` (`inspect.signature` falls back to `(*args, **kwargs)` for C builtins lacking `__text_signature__`).
  Concurrency tests share `run_workers()` from `tests/fixtures.py`.
- `smoke/` — `test_optional_deps.py`: one tiny `@fleche()` round-trip per optional dep (cloudpickle / dill / sqlalchemy / bagofholding / attrs), asserting the second call is served from the backend so the dep is genuinely functional (not just importable).
  Selectable with `pytest -m smoke` (the `smoke` marker is registered in `pyproject.toml`).
  Intended as a pre-release sanity check of the packaged distribution;
  uses `pytest.importorskip`, so absent deps skip rather than fail.

Shared fixtures (in `fixtures.py`):
- `call_storage` / `value_storage` / `storage_backend` — *parametrised* over every concrete backend (memory, pickle/cloudpickle/dill files, bagofholding h5, plus sql for `call_storage` only).
  `call_storage`/`value_storage` pickle parametrizations bake in a fixed `secret_key` so signing is exercised by default;
  `storage_backend` skips `secret_key` to test raw `put`/`get` without signing.
  New backends should be added to these fixtures so they're swept by every consumer test (all three share the `_build_value_storage` / `_build_call_storage` constructors, so a backend is added once).
- `paired_storages` — yields `(value_storage, call_storage)` walked *diagonally* rather than crosswise: requesting `value_storage` and `call_storage` in one test takes their 6x7 Cartesian product, which is what a test needs only if the two halves interact.
  Where it just needs *a* cache per backend, this cycles the shorter list against the longer one for `max(len(values), len(calls))` cases with every backend on either side still present.
- `call_storage` additionally gains `sql_postgres` / `sql_mysql` parametrizations when `FLECHE_TEST_POSTGRES_URL` / `FLECHE_TEST_MYSQL_URL` are set;
  each yields an `Sql` backed by a freshly-created database that is dropped on teardown.
  CI populates these env vars from the `postgres` / `mariadb` service containers in `.github/workflows/tests.yml` (`sql-backends` job).
- `postgres_sql` / `mysql_sql` — single-shot variants of the above (skip when the URL env var is unset).
  Use these in tests targeting dialect-specific concerns rather than a cross-backend sweep;
  the cross-backend `external_sql` fixture in `regression/test_sql_non_sqlite_backends.py` parametrizes over both lazily via `request.getfixturevalue` (declaring both as direct dependencies cascades the unconfigured-side skip onto every test).
- `clean_cache` — yields a fresh in-memory `Cache(ValueMemory, CallMemory)` (does **not** install it as the active cache;
  use `with cache(clean_cache):` if you need that).
- `file_cache` — disk-backed pickle `Cache` rooted at `tmp_path`.

## Other directories

- `benchmarks/` — `benchmark_{digest,integration,storage}.py`,
  `run_benchmarks.py`,
  `compare_results.py` (diff two `results.csv` runs),
  `utils.py`,
  `profile_digest_types.py` (per-type cProfile harness),
  `results.csv`.
- `docs/` — Sphinx sources, grouped by topic: root holds `index`, `installation`, `parallel_execution`;
  `usage/` holds `tldr`, `helpers`, `lazy_call`, `query` (`tldr` first);
  `digests/` holds `digests_as_args`, `digest_equivalence`, `entry_points` (the third-party plug-in page);
  `storage/` holds `configuration`, `destructuring` (figures + prose on destructuring/dedup/`remaining_depth`), `cache_stack`, `security`;
  `dev/` holds `call_lifecycle` (the two-phase `prepare`/`commit`/`abandon` save protocol and the miss/hit sequences behind a decorated call),
  `custom_digests`,
  `extending_destructurer`,
  `function_profile`,
  `ssh_cache`,
  `sql_test_backends`,
  `storage_hierarchy`.
  `docs/figures/` holds `gen_diagrams.py` plus the three destructuring SVGs it generates — the script builds the depicted layouts in real `ValueMemory` stores so the digest labels in the figures match what `notebooks/Destructuring.ipynb` computes — and the two hand-written Graphviz sources `storage_hierarchy.dot` / `storage_mro.dot` with their rendered SVGs (`dot -Tsvg <src> -o <out>`), plus `gen_sequence.py`, which emits `storage_sequence.svg` (a destructured save/load through the MRO, showing the per-entry lock scopes) and `cache_sequence.svg` (cache miss/hit around the two-phase save) — its panels are transcribed from instrumented traces, not from reading the code.
  Every figure SVG is checked in rather than rendered at build time because `.readthedocs.yaml` declares no `apt_packages`, so `dot` cannot be assumed on the builder.
  The HTML theme is `shibuya`, skinned solarized-light/dark with the green accent via CSS custom properties in `docs/_static/custom.css` (which also keeps the "on this page" rail in-flow down to 720px-wide viewports and sets an 18px base font);
  the figure palette in `gen_diagrams.py` is the matching solarized-light set, so retheming the docs means updating both and rerunning the generator.
  `docs/notebooks/` is **symlinks** into `../../notebooks/` (one per notebook);
  the `rendernb.yml` workflow re-executes `notebooks/*.ipynb` in place when a PR carries the `rendernb` label.

- `notebooks/` — usage examples (`FiveMinuteTour`, `GettingStarted`, `Caches`, `CacheStack`, `Destructuring`, `StorageBackends`, `SecureStorage`, `ConcurrentExecution`, `ExtraMethods`, `TransferWorkflow`);
  all are executed by `tests/integration/test_notebooks.py`, which parametrises over `sorted(notebooks/*.ipynb)` so a new notebook is covered automatically — add its `docs/notebooks/` symlink too.
  Optional-dep cells (`ase`, `executorlib` in `FiveMinuteTour`) wrap their imports in `try/except ImportError` so the sweep passes under plain `.[tests]`;
  `ConcurrentExecution.ipynb` pins `multiprocessing.get_context("fork")` because a `forkserver`/`spawn` worker (3.14's default) cannot resolve a function defined in a notebook cell (#840).
  `Destructuring.ipynb` embeds the `docs/figures/` figures as **2x PNG** markdown-cell attachments (no display code;
  PNG because JupyterLab refuses to render `image/svg+xml` attachments) and rebuilds every depicted storage layout in `ValueMemory` so readers can play;
  its digest outputs match the figure labels by content-addressing.
  Running `python docs/figures/gen_diagrams.py` regenerates the SVGs **and** refreshes the notebook's embedded PNGs (`refresh_notebook_attachments`, rasterizing via `rsvg-convert` or `cairosvg`);
  each SVG carries a generated-by comment pointing back at the script.
- `.github/workflows/` — CI: `tests.yml` (PR sweep across 3.11–3.14, persisting the Hypothesis example database as a GitHub artifact so shrunk counter-examples survive across runs, + `sql-backends` job that boots Postgres 16 + MariaDB 11 service containers and sets `FLECHE_TEST_{POSTGRES,MYSQL}_URL`),
  `ty.yml`,
  `test-minimum-deps.yml` (installs every direct dep at its declared floor via `uv pip install --resolution lowest-direct -e ".[tests]"` and runs the suite — `uv pip install` rather than `uv sync` because the universal lock floats deps up through cross-extra constraints and would mask the real minimums),
  `benchmarks.yml`/`benchmarks-main.yml`/`updatebenchmarks.yml`,
  `perf-triage.yml` (Haiku reads the PR diff/description and adds the `benchmark` label when the change touches a hot path — that label is the existing `benchmarks.yml` trigger),
  `rendernb.yml` (re-executes `notebooks/*.ipynb` on PRs labelled `rendernb`),
  `reflow-agent-docs.yml` (on PRs touching `AGENTS.md`/`agents/*.md`, runs `reflow_agent_docs.py` and commits the one-sentence-per-line result back to the branch;
  fork PRs get a failing check instead), `release-please.yml`, `pypi-publish.yml` (trusted-publisher upload triggered by `release: published`;
  #900 flags that it duplicates `release-please.yml`'s `publish` job and both can fire on one release), `claude.yaml` + `ci-failure-summary.yml` (the latter exposes CI status as a tool the in-PR Claude can call).
  Releases use **release-please** (`release-please-config.json`, `.release-please-manifest.json`) — release PRs are opened automatically from conventional-commit history on `main`.

## Design themes / open scope (issue tracker)

Map of open design work.
Issue numbers are the entry points — fetch them before re-litigating.
This section tracks **current state only**: when a PR merges, move whatever an agent needs to know into the reference sections above and delete its entry here.
Git history is the changelog.

**Active design themes**

- **Cache thread-safety / concurrency** (umbrella #444).
  Both layers carry the lock mixins (`BaseCache(OperationContext)`, `Cache(PerKeyLockMixin, BaseCache)`).
  Fixed and regression-pinned: back-fill #217, transfer TOCTOU #452, in-flight dedup window #485.
  #451 (redigest atomicity) has its fix in (PR #631) but the issue stays open pending follow-up review — cite the PR, not "#451 closed".
  Open: `gc` #450, `expand` lock scope #453, gc vs. in-flight prepared calls #826 (see Bugs);
  #448 (wrapper check→execute→save) closed not-planned.
  `BackgroundSaveMixin` (#447) is the planned vehicle for moving disk I/O off the hot path while `save()` keeps returning a key synchronously.

- **Performance hot-spots** (#625, #440).
  The current `Perf audit:` issue is #625, refreshed periodically — read its newest comment for numbers.
  Open:
  - *Digest.* `_digest_bytes` returns hex-encoded bytes that double parent SHA256 input at every nesting level;
    the fix is a raw-bytes swap behind a `hash_version` bump + `Cache.redigest` migration.
    The per-element hash context is load-bearing for the Merkle property and has no cheap fix.
    The hash-function migration is settled on **blake2b(digest_size=32)** (stdlib, ~35–40% faster on tree workloads, 64-char hex preserved so `DIGEST_LENGTH` / SQL schema / `D()` pass-through stay put);
    #615 is the open switchover.
    It invalidates persistent keys, but per the pre-1.0 rule in [Commit messages](#commit-messages) it is not a `BREAKING CHANGE:` commit.
  - *Double lock.* The cache-layer plus storage-layer `PerKeyLockMixin` costs ×1.5–2.0 on memory-backend miss/save (hit/contains unchanged);
    unaddressed.
  - *`BagOfHoldingH5File`.* ~×5 over `PickleFile` on save and 3.8–6.2× on `contains_hit`/`evict` — a full HDF5 file open/close per `put`/`get`.
    Draft PR #786 (below) implements pooled read handles.
  - *`Sql`.* Every `save`/`evict` commits and fsyncs once per key: `journal_mode=WAL` is set but no `synchronous` pragma.
    `PRAGMA synchronous=NORMAL` (safe under WAL) is the cheap fix and still not applied;
    it only closes the `SqlFile`-vs-`SqlMemory` disk gap.
    `SqlMemory` saves are dominated by ORM/session churn, for which the audit proposes `INSERT ... ON CONFLICT` + per-thread session reuse.

- **Distributed / remote caching.** `SshCache` (#551) ships.
  Open: #552 — a `TieredValues` + `GlobusValues` cold tier for HPC value blobs that `Cache.query()` never touches, only `Cache.load_value()` on a hot miss.

- **Config redesign** (#568).
  Next-generation TOML/YAML schema with top-level `value`/`call`/`stash`/`metadata` namespaces and cross-file named references;
  would supersede the current merged-discovery model once the schema firms up.
  Expect a `hash_version`-style migration story.

- **Path / file handling** (#516, #517, #522, #33).
  First-class `Path` support where files are transparently stashed and restored.
  The implementation is **PR #797** (the `temppath` branch): files/directories are stored by *content* (`PathValueMixin` converts them to `FileBlob`/`DirectoryBlob` records over content-addressed `bytes` blobs, wired into every default value storage;
  identical bodies dedupe), and cache hits rematerialize them as `TempPath`s — `Path` subclasses whose backing temp tree lives while any derived path is referenced.
  Nonexistent paths warn and run uncached (#517);
  paths are found inside dicts/lists/tuples/dataclasses/attrs at any depth.
  `isolate=True` removal is PR #523 (closes #522).

- **Query expressiveness** (#87, #82).
  Intent: merge `load`/`query`, add wildcard semantics, possibly dump non-simple metadata into value storage so call storage stays `dict[str, dict[str, Digest]]` while tags stay equality-queryable.

- **Eviction strategies / GC** (#161, #6).
  `Cache.gc()` (mark-and-sweep) exists;
  size/age/LRU eviction policies and automatic orphan collection are open.

- **Digest correctness / extensibility** (#333, `backburner`).
  Planned refactor moves built-in type handlers into an internal dispatch registry that mirrors the user `Hook` list;
  composes with #834.

**Open refactor proposals** (small, well-scoped, no PRs yet)

*Source:*

- #639 split `make_wrapper`'s ~100-line factory (digest-arg expand / lookup-key derive / `_in_flight` dedup / `pre`+exec+`post` / `Future` callback / `isolate` chdir) into named pieces.
- #688 factor the `with self._operation_context(key): …` wrapping out of every per-key `Cache` method.
- #708 a `@register_cache` decorator, mirroring `@register_storage`, so `cache_from_config` stops hand-dispatching on `pool`/`type="ssh"`/`max_size`/etc.
- #710 reshape `SizeLimitedMixin` as a `CacheWrapper` so it composes with `CacheStack`/`ReadOnlyCache` (today it only pairs with `Cache`).
- #711 consolidate the `Cache.redigest` and `CallStorage.transform` re-keying templates.
- #737 collapse `_REMOTE_METHODS` (server), `_CLIENT_METHODS` (client) and the seven `SshCache` forwarder stubs into one shared RPC-method inventory.
- #739 consolidate the two `_DESTRUCTURERS` predicate walks (`DestructuringMixin.save` and `_intern_rec`) into one lookup.
- #760 replace the `if self.prefix_length == 0` branch re-spelled across `BagOfHoldingH5FileBackend._path`/`_lock_path`/`_contains`/`_evict`/`list` with a `_Layout` strategy.
- #761 unify `Cache` and `_MultiCache` fan-out (`expand`/`_shrink` are the same "gather non-misses, combine" shape written twice) via a shared `_sources()` hook;
  composes with #688 and #708.
- #762 extract a shared `_locked_save_if_absent` from `BaseCache._transfer_one` and `CacheStack._backfill`, which close the same per-key TOCTOU with near-identical bodies, so `BackgroundSaveMixin` (#447) inherits the concurrency-safe shape.
- #788 unify the lookup-digest recipe across `Call`, `DigestedCall`, and `LazyCall` (each rebuilds a stub `Call` to hash;
  the "must hash identically" invariant is held only by comments) as free `_lookup_digest`/`_full_digest` functions.
- #789 split `caches.py` (~1000 lines) into a `caches/` subpackage (`base`/`simple`/`wrappers`/`multi`/`size`);
  kills the `caches ↔ config` cycle behind `BaseCache.from_config`'s lazy import.
- #790 a `_save_call(call, key)` upsert primitive so `CallMixin.save` stops doing `contains` → `evict` → `put` (three backend round-trips) and `Sql` can drop its `save` override.
- #809 extract `Cache.gc`'s transitive-closure walk as a reusable reachability primitive (orphan audits, #552's cold-tier scan).
- #832 split `remote.py` (~1000 lines: wire protocol, client, server, redaction, two-phase handlers) into a `remote/` subpackage.
- #833 collapse the duplicated `to_config`/`register_storage` boilerplate across every `Value*`/`Call*` backend pair.
- #834 turn `digest._digest_bytes`'s `match/case` chain into an ordered dispatch table, uniform with the `Hook` registry (composes with #333).
- #835 hoist `_redact_config` / `_redact_url_password` out of `remote.py` into `config.py`, since they operate on `cache_to_config` output (composes with #832).
- #866 `Sql.query`'s client-side `meta_matches` closure is a byte-identical copy of `QueryCall.matches`'s metadata loop — delegate to it.
- #868 config discovery hand-rolls Linux-only XDG conventions despite the "OS Independent" classifier — switch the lowest-priority fallback to `platformdirs` (adds a runtime dependency) or narrow the classifier.
  Needs a product decision;
  #885 is the same problem in `wrapper.py:_get_working_directory_root` (`XDG_CACHE_HOME`, backs `isolate=True`) — decide once for both.
- #884 sqlite URL handling is hand-rolled twice and has drifted: `config._rebase_url` leaves `~`-prefixed sqlite paths alone while `storage.sql._coerce_sqlite_url` expands them;
  correctness is an accident of call order, pinned by no test.
  Proposal: one shared helper on `sqlalchemy.engine.url.make_url`, lazily imported so configs without `url` don't need `sqlalchemy`.
- #901 `Call.from_call` reimplements `bind()` inline on the hottest path;
  one-line delegation fix.
- #902 `Runtime._keys` advertises `cputime`/`systime` even where `resource` is missing (Windows);
  fix mirrors `Tags`' per-instance `keys`.
  Low urgency.
- #920 `SizeLimitedMixin.__post_init__` fully deserializes every call record via `self.query(QueryCall())` just to read keys;
  `self.calls.list()` gives the same set with zero deserialization and also stops `_keys` drifting from storage keys on a cache not yet `redigest()`'d after a hash-version bump.
  Needs a regression test pinning that.
- #921 `CacheWrapper._query` / `FilteringMixin._query` / `_MultiCache._query` call the *public* `.query()` on members (an extra `QueryIterator` + `Indigestible`-catching generator per level).
  Possibly intentional fault isolation — decide that first, pinned by a test where one member raises `Indigestible`.
- #922 `_cache_from_template`'s blanket `except TypeError` re-reports internal builder bugs as "Invalid arguments for cache template …";
  pre-validate with `inspect.signature(builder).bind(**d)` instead.
- #923 `Digest.expand`/`shrink` share an identical lazy-cache preamble (extract `_resolve_cache`);
  the `staticmethod`/`classmethod` match arms are byte-identical (subsumed by #834).
- #944 `cache_to_config` hand-serialises `SshCache` with copy-pasted field defaults;
  give `SshCache` its own `to_config()` like every storage backend.
- #960 dangling value-digest references resolve under three policies: `LazyArguments.__getitem__` degrades to the bare digest, while `LazyCall.result` and `Digested.get` (behind every `mend()`) raise out of ordinary reads.
  Proposal: one `_load_value_or_digest` helper;
  needs a regression test evicting a referenced value.
  Narrower than the parked #93.
- #961 `wrap_executor`'s hit path does `.contains()` then `.load()` — double hashing per hit, and an eviction in between surfaces as an uncaught `KeyError` from `submit()`.
  Mirror the wrapper's single `load` + `except KeyError`;
  needs a regression test evicting between check and read (race family of #450/#453).
- #962 `BaseCache.table` and `QueryIterator.table` docstrings have drifted on `shrink_keys`;
  make the query side authoritative (the `_QUERY_DOC` pattern `wrapper.py` uses).
- #974 `filelock` is a hard dependency but only `bagofholding_file.py` imports it;
  move it into the `bagofholding` extra and defer the import like `h5py`.
  Done carelessly it breaks `import fleche` — re-check `test-minimum-deps.yml` and the optional-dep sweep.
- #975 the `Intent.READ` no-op short-circuit is copied in `SerializingMixin`,
  `PerKeyLockMixin` and `CacheStack._operation_context` — three sites that must change together when a reader-writer lock lands.
  Extract only opportunistically.

*Tests, benchmarks, docs tooling:*

- #791 registry-driven backend fixtures + shared test helpers (`BACKENDS` registry, `mem_cache`/`active_cache`/`make_call`/`blocking_hook_cache`), replacing the per-backend if/elif ladders in `tests/fixtures.py` and `regression/test_sql_non_sqlite_backends.py` and the drifted `PlainValueMemory`/`DestructuringMemory` copies.
- #869 a `make_memory_cache()` helper for the ~100 inline `Cache(ValueMemory({}), CallMemory({}))` sites in `tests/unit/` (regression tests stay self-contained);
  complements #791.
- #899 `tests/strategies.py`'s `dataclasses()` instantiates via `cls(*fields)` — the dict's *keys* — so every synthetic dataclass carries only field-name strings (`namedtuples()` correctly uses `cls(**fields)`).
  Fix with a shared `_draw_fields` helper as its own change;
  newly varied values may surface latent issues.
- #867 `benchmarks/utils.py` is a stale fork of `tests/strategies.py`;
  import the shared strategies.
  #886 `benchmarks/benchmark_storage.py` duplicates its five-op timing harness and `ValueMemoryRaw`;
  factor into `benchmarks/utils.py`.
- #983 `benchmarks/profile_digest_types.py::_categorize` mirrors `digest.py`'s match-arm order and has drifted (DataFrames mislabel as `Iterable`, bound methods as `Indigestible`) — profiler report only, not real digests.
  Durable fix composes with #834;
  stopgap is re-sync plus a one-instance-per-arm pinning test.
- #982 `docs/figures/gen_diagrams.py` / `gen_sequence.py` duplicate palette, fonts, `GEN_NOTE` and the SVG `text()` builder;
  a shared `_svg_common.py`.
  Low priority.

*CI and packaging:*

- #900 `pypi-publish.yml` and `release-please.yml`'s `publish` job duplicate the build+publish steps and both fire on a normal release (PyPI rejects the second upload — a spurious failed run per release).
  Delete the fallback or share a `workflow_call`, pending a decision on whether the fallback is intentional.
- #945 `tests.yml` / `test-minimum-deps.yml` / `ty.yml` triplicate the paths-filter `changes` job;
  #976 `benchmarks.yml` / `benchmarks-main.yml` duplicate their setup preamble;
  #985 the dev Python version (3.12) is hardcoded in four workflows.
  Do these together as reusable workflows / a composite action.
- #946 `updatebenchmarks.yml` / `rendernb.yml` duplicate their commit+push tail and pin `ad-m/github-push-action@master`, a mutable ref with `contents: write` on PR-triggered workflows — the pinning half is a supply-chain fix worth doing on its own.
- #947 `pyproject.toml` repeats version pins across extras instead of self-referential extras (`ssh = ["fleche[cloudpickle]"]`).
  Sanity-check `pip install -e ".[tests]"` and `test-minimum-deps.yml`'s `--resolution lowest-direct` (sensitive to cross-extra constraints) before merging.

**Bugs**

- #826 — `Cache.gc()` can collect the argument values of an in-flight `PreparedCall`: they are stashed in `prepare` but the call record isn't filed until `commit`, so a `gc` in between evicts reachable values.
- #840 — `BoundWrapper` only survives `ProcessPoolExecutor` under `fork`: `spawn`/`forkserver` workers re-import `__main__` to resolve the callable, which fails for notebook-cell functions and non-importable modules.
  Fix in flight as PR #887 (below).
- #893 — multi-bag `bagofholding_file` writes hit `filelock.Timeout` storms under same-bag concurrency: the per-bag lock serialises writers, so with 8 writers any same-bag put ≥ ~150 ms crosses the **1.0 s default `lock_timeout`** (not a deadlock).
  Destructuring makes same-bag collisions routine.
  Suggested fixes: a much larger default, keeping `lock_timeout` configurable (a bagofholding `values.lock_timeout = 60` works today), and/or retry-with-backoff in `put()`.
- #895 — `wrap_executor`'s cache-hit path always returns a plain `concurrent.futures.Future`, while a miss returns the executor's own Future subtype.
  Maintainer decision: a documented limitation, no general fix (a foreign `Future` can't be built without submitting work);
  the issue stays open.
- #903 — pickle-family `put()` dying on `filelock.Timeout` under NFS contention.
  Fixed for the pickle family by the lock-free atomic-rename write in 0.22.0;
  the issue stays open because the multi-bag path is still exposed (#893).
  Same-key contention there comes from content-addressed dedup funnelling every worker sharing a byte-identical sub-object onto one value key's lock — unrelated calls then report the same lock path, which looks like a digest collision but isn't.
- #916 — `.query()` ignores `hash_version=False` / `hash_module=False`: `make_get_call` nulls `version`/`module` out of the lookup key, but `make_query` builds its template with the profile's real values, so it silently matches nothing (`hash_code` is unaffected — the query-side `None` code digest is a wildcard).
  `docs/usage/helpers.rst` warns about it.
  The fix (thread both flags into `make_query` + a parametrized regression test in `tests/unit/fleche/test_decorator_attributes.py` + removal of the docs warnings, including USAGE.md's "Known trap") is on branch `fix/query-hash-flags-916`, no PR yet.
  It is branched off #933's branch, so merge #933 first, then retarget onto `main`.
- #918 — destructuring storage ignores digest hooks, breaking *digestible ⇒ storable*: `digest()` consults `get_hooks()` before any structural walk, but `DestructuringMixin._intern_rec` picks a destructurer purely from `_DESTRUCTURERS` predicates, so a hooked dataclass is torn into its fields and the opaque field the hook avoided raises `Indigestible` on save — naming a type the caller never mentioned.
  Suggested fix: treat hook-covered (or `__digest__`-bearing) values as opaque leaves in `_intern_rec`.
  Composes with #883/#905 and #333.
- #883 — `DestructuringMixin._raw_sub_digests` hardcodes a `match` over the three built-in `Digested` types, so a subclass registered via `register_destructurer` reports zero children: `Cache.gc()` can evict values reachable only through it (silent data loss) and `count_reuses()` under-counts.
  Fix in flight as PR #905 (below).

- Numeric digest collisions — no issue filed yet;
  the full investigation (2026-10-06) lives in a comment on PR #990.
  The `Number` arm digests via `hash(value)`, a lossy 61-bit residue, so distinct numbers share cache keys and produce wrong hits end to end: `digest(-1.0) == digest(-2.0)` (CPython reserves `-1` as an error sentinel),
  `digest(0.5) == digest(2**60)` (rational hashing mod `2**61 - 1`),
  `inf` vs `314159`,
  `np.uint64(2**63)` vs `4`, complex via the `hash(a) + 1000003*hash(b)` formula;
  digests are also platform-dependent (32-bit builds hash mod `2**31 - 1`).
  The Hypothesis pair tests in `digest/test_digest.py` can't draw these coincidences, and the complex test's oracle restates the bug (`hash(x) == hash(y)` ⇒ equal digests) — regression tests need explicit `@example`s.
  A second, separable finding: `digest(3) == digest(3.0)` by design, so equal-value different-type *results* share one value-storage entry and whichever saved last wins the return type.
  The PR comment carries a validated `_digest_number` prototype (digest the exact rational via `as_integer_ratio`, dedicated salts for rational/complex/inf, NaN keeps `struct.pack`;
  full suite green) pending maintainer decisions on unknown `Number` types (raise `Indigestible` vs keep `hash()`) and on result-type erasure.
  The fix invalidates number-bearing keys — pre-1.0 that is a `fix:` per [Commit messages](#commit-messages), and it is worth coordinating with the blake2b switchover #615, which invalidates every key anyway.

**Feature requests**

- #829 — `SshCache` support for `Path` values via client-side blob conversion;
  the `temppath` branch carries the interim `RemotePathUnsupported` refusal.
  Plan: a path *arg* becomes a digest-only reference computed locally, a path *result* is `Rejected`, load raises lazily on `.result` only.
- #854 — opt-in "hard fail on `Indigestible` or argument-stashing errors" mode.
  Tension: fleche's default "stay out of the way" contract (a fleche-stripped program is semantically identical) versus only discovering after a long run that nothing was cached.
- #855 — opt-in `use_dependencies=` decorator kwarg that bakes a `pothenon`-parsed dependency tree into the lookup key (see the [pothenon demo](https://github.com/pyiron/pothenon/pull/36)), so changing a called function invalidates callers without hand-tagging every layer with `version=`/`hash_code=`.

**Field reports**

- #942 — mine it before building anything in this area: migrating ~20k cached calls across a module rename under the default `hash_module=True`.
  The call index was rewritten via `dataclasses.replace(digested_call, module=new)` + `.to_lookup_key()` (reusing fleche's own key derivation), run add-only first against a backup copy, verified by a recompute-counter test (a `contains()` check would pass on a silent recompute), then `--replace` + `VACUUM` (SQLite does not shrink on delete).
  Value storage is untouched — a module rename changes call keys only.
  Wishlist in the issue: a first-class `rename_module`/`rekey` op on `CallStorage` (composes with #711), a module/name histogram query, verify-against-snapshot for replace-mode tools, and mentioning `VACUUM` wherever bulk SQL deletion is discussed.

**In-flight PRs (unmerged — check before touching the same files)**

- #887 — `BoundWrapper.__reduce__` pre-serialises `func` into a standalone bytes payload (plain `pickle` by reference when importable, `cloudpickle` by value otherwise, a clear `TypeError` when cloudpickle is missing), so it survives `spawn`/`forkserver` pools;
  closes #840, regression pin `tests/regression/test_issue_840.py`.
- #786 (draft) — a process-wide cache of read-only `h5py.File` handles for multi-bag files (bounded MRU of 32, `(inode, mtime_ns, size)` invalidation, `locking=False`, writers close the cached handle under the per-bag lock);
  multi-bag `contains` drops from ~240 µs to ~29 µs.
  `evict` deliberately untouched;
  cold `list()` over many bags remains the open cost (options listed in the PR body).
- #804 — drops the `SizeLimitedCache(max_size=10)` benchmark config: uniform-random eviction meant its "hit" samples mostly re-measured misses, so hit-phase numbers for that config in existing `results.csv` runs are unreliable.
- #797 (`temppath`, path-by-content), #523 (`isolate=` removal), and #905 (`ChildItems` interface — record classes implement `child_items()`, `child_digests()` derives from it, so `_raw_sub_digests` becomes one generic reader;
  ships the differential gc test with a custom destructurer;
  `mend` deliberately does not route through `child_items`, ~70% slower for no gain;
  targets the `temppath` branch, closes #883) under the path-handling theme.
- Single-page docs PRs over `docs/`, each mergeable alone:
  - #932 — parallel_execution: MPI example.
  - #933 — usage: `.fleche` namespace, #916, groupby staleness.
    Needs a rebase onto `tldr.rst`/`helpers.rst` as they are on `main`.
  - #934 — SSH config + destructuring list.
    Needs a rebase onto `ssh_cache.rst` as #993 left it.
  - #965 — usage: scope the lazy-return claim to `load()`/`query()`.
  - #989 — parallel_execution: an MPI-decorated call runs once per rank cold and serves one rank's record warm.
  - #990 — digests: the numeric-digest mechanism explanation;
    superseded by its own review — the maintainer judged the rewrite the wrong level ("warrants deeper investigation") and the follow-up investigation on the PR found the digest *code* at fault (see the numeric-digest bullet under **Bugs**), so expect it to close in favour of a code fix rather than merge.

  #932 and #989 both edit `parallel_execution.rst`;
  whichever lands second needs a rebase.
- Test-only coverage sweeps: #939 (pins the `Intent.READ` no-op fast path in both lock mixins;
  drops 11 tests strictly weaker than a sibling;
  converts `test_local_function_digests_same_as_module_level` into `test_nesting_changes_a_function_digest` — `CO_NESTED` is in `co_flags`, so lifting a helper out of an enclosing function invalidates its cached calls under `hash_code=True`;
  pinned as observed, flip it there if ruled a bug), #955 (pins the deferred-future abandon arm in `wrapper.py`;
  collapses five single-property tests in `test_dehydrate.py`), #980 (covers the `storage/sql.py` PRAGMA guards and fixes the dead in-memory journal-mode short-circuit — SQLAlchemy percent-encodes `:memory:`, so the check becomes `engine.url.database in (None, ":memory:")`;
  drops 11 vacuous digest smokes), #1000 (pins the NaN `struct.pack` arm deterministically — two *simultaneously live* same-value NaNs must share a digest, which `hash()`-routing would break since CPython's NaN hash is address-derived;
  covers the `<d` `Decimal`-NaN sub-arm and the `np.bool_` → builtin-`bool` delegation;
  narrows the Hypothesis float/complex pair tests to `allow_nan=False`, killing their self-fulfilling NaN oracle branches;
  drops four digest tests subsumed *in assertion* by siblings, after a per-test-arc ablation confirmed 89% of tests have zero unique arcs — reaffirming the collective-redundancy lesson below;
  also `.gitignore`s `pytest --cov`'s `.coverage` litter;
  the PR body flags the next deterministic-coverage picks, led by `bagofholding_file.py`'s seed-dependent `SaveError` arm).

**Lessons and standing decisions**

- `hash_code=False` stays the default, so a plain `@fleche()` on two closures from one factory still shares a cache entry;
  documented rather than changed, since flipping it invalidates every cache.
  Use `hash_code=True` (which folds captures and defaults into the key) when that matters.
- Cache-key-invalidating changes so far have shipped without a `hash_version` bump (e.g. pandas content digests);
  old entries are simply unreachable until `Cache.redigest()` runs.
  Say so in the commit body.
- Test removal: suite-wide ablation showed redundancy is *collective* — most tests contribute no unique coverage individually, yet deleting them together loses coverage.
  "Covers nothing uniquely" is not a deletion criterion;
  remove only tests strictly weaker than a same-file sibling, and check per-file coverage stays identical.
- README's "Thread-Safe: Safe for use in multi-threaded environments" bullet overclaims and now disagrees with the narrowed `docs/index.rst`;
  the README fix (#950) was closed unmerged without a reason — ask the maintainer before reopening.
- The in-PR Claude app cannot push changes under `.github/workflows/` (its token lacks the `workflows` permission);
  workflow-file edits need a maintainer push.
- `.gitignore` covers `notebooks/*.db*` only, so a stray notebook-run cache file at the repo root can recur.

**Out-of-scope / deferred (do not re-open without reason)**

- MPI-rank-parallel call caching in core (PR #870, closed unmerged) — a `fleche.mpi.collective()` helper was built, tested, and rejected from core;
  an addon package (`fleche-mpi` or similar) is the preferred home, and the close-out comment on #870 is its reference.
  Branch `claude/fleche-mpi-executor-caching-zxjazw` keeps the helper, 13 subprocess-isolated integration tests, and `docs/mpi_execution.rst`.
  Findings that stand regardless: lookup keys carry no rank, so all ranks contend for one record — warm runs flip the `[result, None]` return shape, and divergent per-rank hit/miss decisions make some ranks skip the body's collectives (silently wrong, or a hang).
  What works today: decorate the *submission site*, not the MPI kernel.
  `wrap_executor`'s cold/warm return-shape asymmetry is still undocumented in `docs/parallel_execution.rst` (#989 adds the per-rank warning).
- Optional skip-saving of input arguments (#170), corruption-tolerant loads (#93), method-state restoration (#99), metadata-into-value-storage (#82) — parked for milestone 2.0.
- Refactors flagged `backburner`: `_digest` dispatch registry (#333), `DigestedCall`/`LazyCall` consolidation (#404).
- Terminology shift "cache" → "stash" and unifying "hash"/"digest" on "digest" (#350) — targeted for 1.0, not started.
- The function-attribute namespace is `.fleche.*`;
  the broader naming discussion (#222) is open but no rewrite is queued.
- "Cache-oriented programming" patterns (#70) remain exploratory.

## Commit messages

Always write commit messages in the [Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/) format (`<type>[optional scope]: <description>`, e.g. `feat:`, `fix:`, `docs:`, `test:`, `chore:`, `refactor:`).
This repo's releases are driven by **release-please**, which derives version bumps and changelog entries from the conventional-commit history on `main` — non-conforming messages are ignored by the release tooling.
Use `!` after the type/scope (or a `BREAKING CHANGE:` footer) for breaking changes — **but never while the project is below 1.0**.
Release-please turns a breaking marker on an `0.x` version into `1.0.0`, so a change that merely invalidates cache keys would cut the first stable release as a side effect.
Pre-1.0, such a change is a `fix:` (or `feat:`) whose body explains the invalidation and points at `Cache.redigest()`;
the version bump is not the place to carry that warning.

## Commit attribution

When running inside a GitHub Action, the workflow may be authenticated with a user PAT (see `.github/workflows/claude.yaml`).
Without intervention, any commits you create would be attributed to that user.
Always attribute your commits to the bot identity instead:

```
git -c user.name="claude[bot]" \
    -c user.email="claude[bot]@users.noreply.github.com" \
    commit --author="claude[bot] <claude[bot]@users.noreply.github.com>" ...
```

Or set the identity once per session:

```
git config user.name "claude[bot]"
git config user.email "claude[bot]@users.noreply.github.com"
```

and pass `--author="claude[bot] <claude[bot]@users.noreply.github.com>"` on every `git commit`.
This applies to amends, rebases, and squash-merges too.
