# AGENTS.md

Reference for AI coding agents working in this repository.

## Quick Reference

**What:** Persistent function cache (`@fleche()` decorator) — like `lru_cache` but survives restarts. SHA256 content-based keys, pluggable backends.

**Entry points:** `wrapper.py` (decorator) → `call.py` (key building) → `digest.py` (hashing) → `caches.py` (cache objects) → `storage/` (backends).

**Active cache:** `ContextVar` in `state.py`, initialised **at import time** via `config.load_cache_config()`. `cache(c)` sets it and returns a sticky context manager — enter/exit as `with` to restore, or discard the return value to keep the change. `cache()` with no args returns the current cache. `cache(name_or_obj, stack=True)` builds a `CacheStack` with the new cache at `stack[0]` (the primary save/load target) and the previous active cache as fallback. Config auto-loads from `./fleche.toml` first; if missing, tries `$XDG_CONFIG_HOME/fleche/cache.toml` when that env var is set, otherwise `~/.fleche.toml` (the two globals are mutually exclusive, not chained). Falls back to a `Cache(ValueMemory, CallMemory)` when no file is found.

**Public API (`fleche.__init__`):** `fleche`, `cache`, `meta`, `tags`, `project`, `BoundWrapper`, `Ignored`, `Required`, `D`, `wrap_executor`. `D(value)` returns a `Digest`: short hex strings (≤64 chars, hex-only) pass through verbatim so they can be used as lookup keys; anything else is digested. `Digest` args to a wrapped function are auto-expanded before hashing.

**Backends (config `type` strings):** `"memory"`, `"void"`, `"pickle"` / `"cloudpickle"` / `"dill"` (filesystem with chosen serializer), `"bagofholding_hdf"` (HDF5), `"sql"` (SQLAlchemy, **calls only**). Values and calls are stored separately so call records are queryable without deserializing heavy values.

**Key files:**
| File | Role |
|------|------|
| `wrapper.py` | `@fleche()` decorator; re-exports `Ignored`/`Required` from `call.py`; `process_ignore_required_args` merges explicit `ignore=`/`require=` args into a `FunctionProfile` via `dataclasses.replace`; attaches `.call/.digest/.load/.contains/.query/.rerun/.bind` helpers (also under `.fleche.*`) |
| `digest.py` | `Digest(str)` (with `.expand`/`.shrink`); `digest()` (SHA256 hex); `Hook`, `add_hook`, `get_hooks`, `load_entry_points`; `Unhashable`; `DIGEST_LENGTH=64`. Built-in types (numpy scalars/arrays, complex/Number, dataclasses, attrs instances, dicts, iterables, `FunctionType`/`CodeType`, `datetime.{timezone,timedelta,datetime,date,time}`) are inline `match` cases in `_digest`. User types opt in by defining `__digest__` on the class — checked before the built-in cases so dict/list subclasses can override (negative answers are cached in `_TYPES_WITHOUT_DIGEST` to keep the hot path one set lookup). The `Hook` registry (`add_hook`) and entry-point plugin loading (`[project.entry-points."fleche"]`, key `digest`) are for *third-party* types you can't modify; entry points are lazy-loaded on first `Unhashable` and retried once. NaN floats are packed via `struct.pack` (sign-preserving) instead of going through `hash()`; complex NaNs use `<dd`. |
| `_attrs.py` | Internal `is_attrs_instance` / `field_items` helpers gating optional `attrs` support; safe to import without `attrs` installed. |
| `call.py` | `Call` dataclass (`from_call`, `to_lookup_key`, `.stash(values)→DigestedCall` writes args+result to value storage / `.digest()→DigestedCall` digests without saving); `DigestedCall` (storage representation: arguments and result are `Digest` keys; `.fetch(cache)→LazyCall`); `LazyCall` (private `_arguments`/`_result`, deferred deser via `_cache`; `LazyArguments` Mapping resolves digests on access; `.fetch()→Call` materialises every value into a plain `Call`); `QueryCall` (wildcard match via `matches`, built via `partial=True` binding — does *not* implement `__digest__`); `bind()` wrapper over `inspect.Signature.bind[_partial]`; `AnyCall = Call \| LazyCall`. `Call`, `DigestedCall`, and `LazyCall` digest identically when their fields agree. `Ignored`/`Required` marker classes live here (re-exported via `wrapper.py` for the public API). All static per-function metadata (signature, qualname, module, version, `code_digest`, ignored/required arg sets) is consolidated in the frozen `FunctionProfile` dataclass; `FunctionProfile.of(func)` performs every introspection step; `_profile` is a single `lru_cache(maxsize=1000)` backing `_get_profile()`, which handles unhashable callables via `_profile.__wrapped__`. |
| `caches.py` | `BaseCache`, `Cache`, `CacheStack`, `ReadOnlyCache`, `FilteredCache`, `RefreshingCache`, `SizeLimitedMixin`/`SizeLimitedCache`; `Rejected` exception. Wrapper-cache scaffolding: `CacheWrapper` (forwarding base — every `BaseCache` method delegates to `self.cache`) plus behaviour mixins `ReadOnlyMixin` (turns `save`/`evict` into `Rejected`) and `FilteringMixin` (filters `load`/`_query` by a predicate). `ReadOnlyCache = ReadOnlyMixin`, `FilteredCache = FilteringMixin + ReadOnlyMixin`, `RefreshingCache = CacheWrapper` overriding `load`/`contains` to always miss — extend by mixing these the same way. On `BaseCache`: `transfer(other, pop=False, overwrite=False)` (skips conflicts unless `overwrite`; only evicts from source on `pop` when actually transferred), `readonly`, `push`, `filter`, `table`, `query(template_or_None, **kwargs)` (template *or* kwargs, not both). On `Cache` only: `redigest` (re-saves any call whose `to_lookup_key()` no longer matches its stored key — used after a hash-function change); `gc` (mark-and-sweep: walks every stored call to collect reachable value digests, transitively follows sub-references via :meth:`DestructuringMixin.child_digests` when the value storage satisfies `HasChildDigests`, then evicts every unreachable `values` key; call records untouched). `Cache.contains` short-circuits to `self.calls.contains(key)` (no value deser); `BaseCache.contains` falls back to load+catch. `Cache.expand`/`shrink` aggregate over `(self.calls, self.values)`; `CacheStack.expand`/`shrink` aggregate over the stack — both via the private `_combine_expand`/`_combine_shrink` helpers, which raise `AmbiguousDigestError` when sub-storages disagree on the full digest. `CacheStack._query` iterates `stack[0]→stack[-1]` and dedupes by `to_lookup_key()` (so a hit in `stack[i]` hides duplicates in `stack[j>i]`). `CacheStack` saves to `stack[0]` (the codebase calls this the "bottom" / "lowest" cache; `stack[i>0]` are "higher"); load iterates `stack[0]→stack[-1]` and back-fills any hit on `stack[i>0]` into `stack[0]`. `push(c)` always inserts `c` at `stack[0]`, so the freshly-pushed cache becomes the primary save target with previous layers as fallbacks. Cannot nest (`__post_init__` rejects `CacheStack` members). |
| `state.py` | `cache()`, `meta()`, `tags()`, `project()`; `_StickyContext` (backport of Py3.14 Token CM); `BoundWrapper` (freezes cache + metadata for pickling) |
| `query.py` | `QueryIterator` over `LazyCall` — lazy: `take/skip/filter/unique/results`; eager (consume the iterator): `only/any/count/empty/sorted/groupby/latest/oldest/evict/table`. `.table()` → pandas DataFrame (auto-converts `timestart`/`timestop` to local tz; argument names that clash with built-in/metadata columns are prefixed `a_`). `latest`/`oldest` need `Runtime` metadata. `sorted`/`unique`/`groupby` accept either a callable or an argument-name string (resolved via `_resolve_key` to `c.arguments[name]`). |
| `metadata.py` | `MetaData` ABC: only `name` and `keys` (schema dict) are abstract; `pre(call)` / `post(pre, call)` are concrete and default to `{}`. Returns must be JSON-serialisable (`JSONValue` alias). Built-ins: `Runtime` (timestart/timestop/walltime, name=`"runtime"`), `Tags` (name=`"tags"`, dict of user-supplied tags; each tag becomes its own column in `.table()`). |
| `config.py` | TOML loader (`load_cache_config`, `load_default_metadata`); `storage_from_config`/`storage_to_config`, `cache_from_config`/`cache_to_config` (round-trippable); `_live_caches` interns named caches. `load_cache_config` routes through `cache_from_config`, so TOML honours `max_size`, `read_only`, and array-of-tables list-stack configs identically to the programmatic API. See module docstring for full type reference and TOML examples. |
| `security.py` | `SignedBytes` HMAC-SHA256 wrapper (hex-encoded so it never contains pickle STOP, which is how `loads` finds the signature boundary); `SignatureError`; `normalize_secret_key`/`get_secret_key`; `FLECHE_SECRET_KEY` env var (colon-separated hex) / `secret_key` config key |
| `executor.py` | `wrap_executor(executor)` monkey-patches `.submit`: cached fleche calls skip the executor and return a pre-completed `Future`; misses are auto-`bind()`'d so cache/metadata context reaches the worker. Splits off executor-reserved kw-only params (e.g. `resources=`) from payload kwargs. Idempotent (`submit._fleche_wrapped`). |

**Storage layout (`storage/`):**
- `base.py` — `KeyManagement` (`list`/`_evict`/`_contains` abstract; `evict`/`contains`/`expand`/`shrink`/`_normalize_key` concrete; `_operation_context` hook — chain via `super()._operation_context(key)`; `expand` raises `KeyError` for prefixes shorter than 4 chars) → `StorageBackend` (adds `put`/`get`) → domain ABCs `ValueStorage`, `CallStorage` (the latter also exposes `transform(func)` — re-saves every entry through *func*, useful after digest changes; the analogous `Cache.redigest` does its own loop because it must update `values` too). → **bridge mixins** `ValueMixin`/`CallMixin` that implement `save`/`load`[/`query`] on top of `put`/`get`. Also: `SaveError`, `AmbiguousDigestError`, `_resolve_prefix` (used by both base and `Sql`).
- `file.py` — `FileStorage` base for disk-backed backends. Locking is via `py-filelock`: writes use `filelock.FileLock(lock_path, timeout=lock_timeout)` directly; reads go through `_file_read_lock_with_fallback`, which on lock timeout logs a warning and proceeds **without** the lock (a missing/torn file then surfaces as `KeyError`). `root` is resolved (`expanduser`+`absolute`+`resolve`) in `__post_init__`. Subclasses implement `_to_file`/`_from_file`; compression and signing live in `pickle_file.py`, not here.
- `memory.py`, `void.py`, `pickle_file.py` (+`PickleFileBackend.with_pickle`/`with_cloudpickle`/`with_dill`; `compress_all`/`decompress_all` migration helpers; gzip auto-detected by `\x1f\x8b` magic on read), `bagofholding_file.py`, `sql.py` — concrete backends (each exposes `Value*` and/or `Call*` classes; `sql.py` only has `Sql` for calls). `MemoryBackend.put`/`get` deep-copy values, so mutating a stored object after retrieval does not affect later reads. `Sql.query` always pushes name/module/version/code_digest/result and argument filters down to SQL (arguments are compared as `digest(value)` strings via `JOIN`s on the `arguments` table). Metadata filters are pushed down only when *every* filter value is a simple scalar (`str`/`bool`/`int`/`float`) via JSON-extract `as_*` casts; any `None` or complex (e.g. list) value disables metadata pushdown only — name/argument filters still apply at SQL level — and the post-load `meta_matches` check runs on every yielded result regardless. `_coerce_sqlite_url` accepts a bare path (treated as sqlite, parent dir auto-created), a `sqlite:` URL, or any other SQLAlchemy URL (e.g. `postgresql://`, `mysql+pymysql://`) verbatim. `:memory:` is special-cased. SQLite foreign-key enforcement is enabled via a `connect`-event PRAGMA, gated on `dialect.name == "sqlite"`. The schema is three tables: `calls`, `arguments` (one row per arg, `UNIQUE(call_key, name)`, ordered by `position`), `metadata` (one JSON blob per metadata namespace, `UNIQUE(call_key, name)`). MySQL/MariaDB needs explicit `VARCHAR(255)` for indexable name columns; other dialects get unbounded `TEXT` via `String().with_variant(...)`.
- `destructuring.py` — `DestructuringMixin` for recursive value splitting + `Digested` ABC with markers `DigestedIterable` (lists/tuples), `DigestedDict`, and `DigestedFields` (shared base reconstructing instances via `object.__new__` + `__setattr__`, bypassing `__init__`/`__post_init__`, so `init=False`/`InitVar`/frozen/slots fields round-trip) with two concrete subclasses `DigestedDataclass` (stdlib dataclasses) and `DigestedAttrs` (`attrs`-decorated classes). All preserve digest equivalence via `__digest__`. `DestructuringMixin` is a `ValueStorage` subclass — operates at the `save`/`load` layer, not `put`/`get`; compose **above** `ValueMixin` in the MRO. `remaining_depth` (default `0`) controls how deep structures are split across keys. `child_digests(key)→set[Digest]` returns the immediate digest references of a stored entry (raw, pre-`mend`); `count_reuses()` tallies how often each key is referenced as a sub-component (useful for GC-style audits). The `HasChildDigests` `runtime_checkable` Protocol declares the `child_digests` shape so `Cache.gc()` can opt-in to transitive walks via plain `isinstance` — any future value storage that exposes `child_digests` satisfies it without explicit registration. NamedTuples are deliberately **not** destructured (`_is_trojan_tuple` guard).
- `thread_safe.py` — `SerializingMixin` (single `_PicklableRLock`), `PerKeyLockMixin` (striped locks via a module-level `_per_instance_locks: WeakKeyDictionary`; per-instance `WeakValueDictionary[key, RLock]` — so the storage instance must be **hashable**, which all the frozen-dataclass concrete classes are); `_PicklableLock`/`_PicklableRLock` (survive pickle round-trip, state not preserved — in-process only, NOT inter-process synchronisation).

**Storage class composition:** Concrete classes are `@dataclass(frozen=True)` and inherit via MRO. Thread-safety mixins are **already baked into** the disk-backed classes — do not wrap them again:
- `ValueMemory(DestructuringMixin, ValueMixin, MemoryBackend)`
- `CallMemory(CallMixin, MemoryBackend)`
- `ValuePickleFile(PerKeyLockMixin, DestructuringMixin, ValueMixin, PickleFileBackend)`
- `CallPickleFile(PerKeyLockMixin, CallMixin, PickleFileBackend)`
- `ValueBagOfHoldingH5File`/`CallBagOfHoldingH5File` — same pattern (PerKeyLock + [Destructuring] + …Mixin + BagOfHoldingH5FileBackend)
- `Sql(PerKeyLockMixin, CallStorage)` — bespoke; bypasses `StorageBackend`/`CallMixin`, implements `put`/`get`/`query` directly against SQLAlchemy; `__reduce__` reconstructs from `(url, echo)`

Each mixin/backend declares its own dataclass fields; Python's dataclass machinery merges them into one generated `__init__` via MRO — **do not pass `init=False`** on user-facing fields. Internal state (locks, `_keys` on `SizeLimitedMixin`, `engine`/`session`/`_local` on `Sql`) uses `field(init=False, repr=False, compare=False)` and is rebuilt in `__post_init__` via `object.__setattr__`. `config._asdict_init_only` strips `init=False` fields when serialising, so any new internal field must be `init=False` or it leaks into round-tripped configs.

---

## Commands

```bash
pip install -e ".[tests]"                              # install with test deps
pytest tests/                                          # all tests
pytest tests/unit/digest/test_digest.py::test_name     # single test
ty check src/                                          # type check (CI: .github/workflows/ty.yml)
python benchmarks/run_benchmarks.py                    # benchmarks (writes benchmarks/results.csv)
```

Python `>=3.11,<3.15`. No committed lint config; `pyproject.toml` has no `[tool.ruff]`/`[tool.flake8]`.

Optional dep extras: `cloudpickle`, `dill`, `sqlalchemy`, `bagofholding`, `executorlib`, `docs`, `tests` (the `tests` extra already pulls in cloudpickle/dill/sqlalchemy/bagofholding/attrs). `attrs` itself has no dedicated extra — it is only required to exercise the `attrs`-class digest/destructuring paths in tests; runtime support degrades gracefully when `attrs` is missing. Other optional deps are gated via `pyiron_snippets.import_alarm.ImportAlarm` — importing a backend without its extra installed raises at construction, not at module import.

## Architecture notes

### Core data flow

1. `@fleche()` wraps a function; on construction it builds a `FunctionProfile` (signature, qualname, module, version, code_digest, ignored/required arg sets — from `Ignored`/`Required` annotations and explicit `ignore=`/`require=` decorator args).
2. On call: `Digest` args auto-expanded → `Call.from_call()` binds via signature (applies defaults) → policy strips ignored args → `.to_lookup_key()` → `digest()` (SHA256 hex).
3. Hit → return stored result. Miss → run `pre` metadata hooks, execute, run `post` hooks, save `Call` + result. If result is a `Future`, save is attached as `add_done_callback`.
4. Active cache is a `ContextVar` — thread-safe, switchable via `with cache(my_cache):`.
5. Special cases: `None` return → not cached (warning). `Unhashable` arg → call runs uncached. Missing `Required` kwargs → call runs uncached.

### Cache key control

Decorator kwargs (`wrapper.py`): `version`, `meta`, `hash_version`, `hash_module`, `hash_code` (hashes `func.__code__`), `require`/`ignore` (arg name lists), `isolate` (runs in a unique tempdir under `$XDG_CACHE_HOME/fleche/cwd/`, defaulting to `~/.cache/fleche/cwd/` when the env var is unset — **not thread-safe**, uses `os.chdir`). Per-argument markers are `Ignored[T]` / `Required[T]`. Bump `version=` to invalidate without changing code; `Required` kwargs not explicitly passed make a call run uncached (warning logged).

### Config

Authoritative type-string reference and a worked TOML example live in `config.py`'s module docstring. Two API layers:

- `cache_from_config(d)` shape-dispatches: list → `CacheStack`; dict with `max_size` → `SizeLimitedCache`; dict with `read_only: true` → wraps in `ReadOnlyCache`; else plain `Cache`.
- `load_cache_config(name)` is the TOML loader (called at import time from `state.py`); routes through `cache_from_config`. `"memory"` / `"void"` are special-cased and bypass the file. `metadata = [...]` only accepts `"Runtime"` — `"Tags"` raises (needs arguments).

### Security (optional)

Only pickle-family backends are signed. Key rotation: first key in the list signs, all keys are tried on verify. `SignatureError` raised by `SignedBytes.loads` is caught in `PickleFileBackend._from_file` and re-raised as `KeyError` — so tampered or wrong-key entries behave like a cache miss instead of crashing the program.

## Test layout

`tests/` has `conftest.py` (registers `tests.fixtures` as a pytest plugin), `fixtures.py`, `strategies.py` (hypothesis strategies), and three subtrees: `unit/`, `integration/`, `regression/`.

- `unit/` — one subdirectory per module under test (`caches/`, `call/`, `config/`, `digest/`, `fleche/`, `metadata/`, `storage/`); filenames mirror the feature being tested. Two top-level files: `test_cache_sticky.py` (sticky `cache()` context semantics) and `test_pickle.py` (pickling caches/wrappers).
- `integration/` — `test_integration.py` (main), `test_notebooks.py` (exercises `notebooks/`), `test_parallel_execution.py`, `test_methods.py`, `test_wrapper_query_integration.py`, `test_hash_code_integration.py`.
- `regression/` — `test_issue_{297,319,352}.py`, `test_sql_concurrent_save.py`, `test_sql_table_uniqueness.py`, `test_sql_non_sqlite_backends.py`.

Shared fixtures (in `fixtures.py`):
- `call_storage` / `value_storage` / `storage_backend` — *parametrised* over every concrete backend (memory, pickle/cloudpickle/dill files, bagofholding h5, plus sql for calls only). The pickle-family fixtures use a fixed `secret_key` so signing is exercised by default. New backends should be added to these fixtures so they're swept by every consumer test.
- `call_storage` additionally gains `sql_postgres` / `sql_mysql` parametrizations when `FLECHE_TEST_POSTGRES_URL` / `FLECHE_TEST_MYSQL_URL` are set; each yields an `Sql` backed by a freshly-created database that is dropped on teardown. CI populates these env vars from the `postgres` / `mariadb` service containers in `.github/workflows/tests.yml` (`sql-backends` job).
- `postgres_sql` / `mysql_sql` — single-shot variants of the above (skip when the URL env var is unset). Use these in tests targeting dialect-specific concerns rather than a cross-backend sweep; the cross-backend `external_sql` fixture in `regression/test_sql_non_sqlite_backends.py` parametrizes over both lazily via `request.getfixturevalue` (declaring both as direct dependencies cascades the unconfigured-side skip onto every test).
- `clean_cache` — yields a fresh in-memory `Cache(ValueMemory, CallMemory)` (does **not** install it as the active cache; use `with cache(clean_cache):` if you need that).
- `file_cache` — disk-backed pickle `Cache` rooted at `tmp_path`.

## Other directories

- `benchmarks/` — `benchmark_{digest,integration,storage}.py`, `run_benchmarks.py`, `utils.py`, `results.csv`.
- `devnotes/storage-hierarchy.{dot,md,svg}` — rendered inheritance diagram for the storage classes.
- `docs/` — Sphinx sources, grouped by topic: root holds `index`, `installation`, `parallel_execution`; `usage/` holds `helpers`, `lazy_call`, `query`; `digests/` holds `digests_as_args`, `digest_equivalence`; `storage/` holds `configuration`, `cache_stack`, `security`; `dev/` holds `custom_digests`, `developer`. `docs/notebooks/` is **symlinks** into `../../notebooks/` (six entries — `Caches` and `TransferWorkflow` are not exposed in docs); the `rendernb.yml` workflow re-executes `notebooks/*.ipynb` in place when a PR carries the `rendernb` label.
- `notebooks/` — usage examples (`GettingStarted`, `Caches`, `CacheStack`, `StorageBackends`, `SecureStorage`, `ConcurrentExecution`, `ExtraMethods`, `TransferWorkflow`); five of these (all except `Caches`, `ConcurrentExecution`, `TransferWorkflow`) are executed by `tests/integration/test_notebooks.py`.
- `.github/workflows/` — CI: `tests.yml`, `ty.yml`, `benchmarks.yml`/`updatebenchmarks.yml`, `rendernb.yml`, `pypi-publish.yml`.

## PR and Issue notes

If tasked to work in a 'separate issue/PR' keep your detailed response there and only add a quick link to the original
issue or PR.

# General Instructions

When you cannot complete a task or question because you are missing dependencies fail early and report the errors.

## Commit attribution

When running inside a GitHub Action, the workflow may be authenticated with a
user PAT (see `.github/workflows/claude.yaml`). Without intervention, any
commits you create would be attributed to that user. Always attribute your
commits to the bot identity instead:

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

and pass `--author="claude[bot] <claude[bot]@users.noreply.github.com>"` on
every `git commit`. This applies to amends, rebases, and squash-merges too.
