# AGENTS.md

Reference for AI coding agents working in this repository.

## Quick Reference

**What:** Persistent function cache (`@fleche()` decorator) — like `lru_cache` but survives restarts. SHA256 content-based keys, pluggable backends.

**Entry points:** `wrapper.py` (decorator) → `call.py` (key building) → `digest.py` (hashing) → `caches.py` (cache objects) → `storage/` (backends).

**Active cache:** `ContextVar` in `state.py`, initialised **at import time** via `config.load_cache_config()`. `cache(c)` sets it and returns a sticky context manager — enter/exit as `with` to restore, or discard the return value to keep the change. `cache()` with no args returns the current cache. `cache(name_or_obj, stack=True)` pushes it on top as a `CacheStack`. Config auto-loads from `./fleche.toml`, `$XDG_CONFIG_HOME/fleche/cache.toml`, or `~/.fleche.toml` (in that order) via `config.py`; falls back to a `Cache(ValueMemory, CallMemory)` if none exists.

**Public API (`fleche.__init__`):** `fleche`, `cache`, `meta`, `tags`, `project`, `BoundWrapper`, `Ignored`, `Required`, `D`, `wrap_executor`. `D(value)` returns a `Digest`: short hex strings (≤64 chars, hex-only) pass through verbatim so they can be used as lookup keys; anything else is digested. `Digest` args to a wrapped function are auto-expanded before hashing.

**Backends (config `type` strings):** `"memory"`, `"void"`, `"pickle"` / `"cloudpickle"` / `"dill"` (filesystem with chosen serializer), `"bagofholding_hdf"` (HDF5), `"sql"` (SQLAlchemy, **calls only**). Values and calls are stored separately so call records are queryable without deserializing heavy values.

**Key files:**
| File | Role |
|------|------|
| `wrapper.py` | `@fleche()` decorator; `Ignored`/`Required` arg markers (via `__class_getitem__` → `Annotated`); `ArgumentPolicy`; attaches `.call/.digest/.load/.contains/.query/.rerun/.bind` helpers (also under `.fleche.*`) |
| `digest.py` | `Digest(str)` (with `.expand`/`.shrink`); `digest()` (SHA256 hex); `Hook`, `add_hook`, `get_hooks`, `load_entry_points`; `Unhashable`; `DIGEST_LENGTH=64`; entry-point hooks for numpy/complex/etc. lazy-loaded on first `Unhashable`. |
| `call.py` | `Call` dataclass (`from_call`, `to_lookup_key`); `LazyCall` (private `_arguments`/`_result`, deferred deser via `_cache`; `LazyArguments` Mapping resolves digests on access); `QueryCall` (wildcard match via `matches`, `partial=True` binding); `bind()` wrapper over `inspect.Signature.bind[_partial]`; `AnyCall = Call \| LazyCall` |
| `caches.py` | `BaseCache`, `Cache`, `CacheStack`, `ReadOnlyCache`, `FilteredCache`, `RefreshingCache`, `SizeLimitedMixin`/`SizeLimitedCache`; `Rejected` exception; `Cache.transfer`, `.readonly`, `.push`, `.filter`, `.table`, `.redigest`. `CacheStack` saves to bottom (`stack[0]`), loads top-down and back-fills hits to bottom; cannot nest. |
| `state.py` | `cache()`, `meta()`, `tags()`, `project()`; `_StickyContext` (backport of Py3.14 Token CM); `BoundWrapper` (freezes cache + metadata for pickling) |
| `query.py` | `QueryIterator` — lazy helpers: `only/any/count/empty/take/skip/filter/sorted/unique/groupby/latest/oldest/evict/results/table`; `.table()` → pandas DataFrame (auto-converts `timestart`/`timestop` to local tz). `latest`/`oldest` need `Runtime` metadata. |
| `metadata.py` | `MetaData` ABC (abstract `pre`/`post` → `dict[str, JSONValue]`, abstract `name` and `keys` schema); `JSONValue` type alias; built-ins `Runtime` (timestart/timestop/walltime, name=`"runtime"`), `Tags` (name=`"tags"`, flattens to columns) |
| `config.py` | TOML loader (`load_cache_config`, `load_default_metadata`); `storage_from_config`/`storage_to_config`, `cache_from_config`/`cache_to_config` (round-trippable); `_live_caches` interns named caches. **TOML loading goes through `_create_cache` and only ever produces a plain `Cache`** — `max_size`/`read_only`/list-stack configs in TOML are silently ignored (`cache_from_config`'s shape dispatch is not wired to the loader). See module docstring for full type reference. |
| `security.py` | `SignedBytes` HMAC-SHA256 wrapper (hex-encoded so it never contains pickle STOP, which is how `loads` finds the signature boundary); `SignatureError`; `normalize_secret_key`/`get_secret_key`; `FLECHE_SECRET_KEY` env var (colon-separated hex) / `secret_key` config key |
| `executor.py` | `wrap_executor(executor)` monkey-patches `.submit`: cached fleche calls skip the executor and return a pre-completed `Future`; misses are auto-`bind()`'d so cache/metadata context reaches the worker. Splits off executor-reserved kw-only params (e.g. `resources=`) from payload kwargs. Idempotent (`submit._fleche_wrapped`). |

**Storage layout (`storage/`):**
- `base.py` — `KeyManagement` (`list`/`_evict`/`_contains` abstract; `evict`/`contains`/`expand`/`shrink`/`_normalize_key` concrete; `_operation_context` hook — chain via `super()._operation_context(key)`) → `StorageBackend` (adds `put`/`get`) → domain ABCs `ValueStorage`, `CallStorage` (the latter also defines `transform()`, used by `Cache.redigest`) → **bridge mixins** `ValueMixin`/`CallMixin` that implement `save`/`load`[/`query`] on top of `put`/`get`. Also: `SaveError`, `AmbiguousDigestError`, `_resolve_prefix` (used by both base and `Sql`).
- `file.py` — `FileStorage` base for disk-backed backends: locking (`file_write_lock`/`file_read_lock` with exponential backoff and stale-lock fallback), `root` resolution (expanduser+absolute+resolve in `__post_init__`), `_to_file`/`_from_file` hooks. Compression and signing live in `pickle_file.py`, not here.
- `memory.py`, `void.py`, `pickle_file.py` (+`PickleFileBackend.with_pickle`/`with_cloudpickle`/`with_dill`; `compress_all`/`decompress_all` migration helpers; gzip auto-detected by `\x1f\x8b` magic on read), `bagofholding_file.py`, `sql.py` — concrete backends (each exposes `Value*` and/or `Call*` classes; `sql.py` only has `Sql` for calls).
- `destructuring.py` — `DestructuringMixin` for recursive value splitting + `DigestedIterable`/`DigestedDict`/`Digested` markers (preserve digest equivalence via `__digest__`). Subclass of `ValueStorage` — operates at the `save`/`load` layer, not `put`/`get`; compose **above** `ValueMixin` in the MRO. `remaining_depth` (default `0`) controls how deep structures are split across keys. `count_reuses()` reports how often each key is referenced as a sub-component (useful for GC-style audits). NamedTuples are deliberately **not** destructured (`_is_trojan_tuple` guard).
- `thread_safe.py` — `SerializingMixin` (single `_PicklableRLock`), `PerKeyLockMixin` (striped locks via a module-level `_per_instance_locks: WeakKeyDictionary`; per-instance `WeakValueDictionary[key, RLock]`); `_PicklableLock`/`_PicklableRLock` (survive pickle round-trip, state not preserved — in-process only, NOT inter-process synchronisation).

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

Python `>=3.11,<3.14`. No committed lint config; `pyproject.toml` has no `[tool.ruff]`/`[tool.flake8]`.

Optional dep extras: `cloudpickle`, `dill`, `sqlalchemy`, `bagofholding`, `executorlib`, `docs`, `tests` (the `tests` extra already pulls in cloudpickle/dill/sqlalchemy/bagofholding). Optional deps are gated via `pyiron_snippets.import_alarm.ImportAlarm` — importing a backend without its extra installed raises at construction, not at module import.

## Architecture notes

### Core data flow

1. `@fleche()` wraps a function; on construction it precomputes `ArgumentPolicy` (ignored/required args, from `ignore=`/`require=` or `Ignored`/`Required` annotations).
2. On call: `Digest` args auto-expanded → `Call.from_call()` binds via signature (applies defaults) → policy strips ignored args → `.to_lookup_key()` → `digest()` (SHA256 hex).
3. Hit → return stored result. Miss → run `pre` metadata hooks, execute, run `post` hooks, save `Call` + result. If result is a `Future`, save is attached as `add_done_callback`.
4. Active cache is a `ContextVar` — thread-safe, switchable via `with cache(my_cache):`.
5. Special cases: `None` return → not cached (warning). `Unhashable` arg → call runs uncached. Missing `Required` kwargs → call runs uncached.

### Cache key control

Decorator kwargs (`wrapper.py`): `version`, `meta`, `hash_version`, `hash_module`, `hash_code` (hashes `func.__code__`), `require`/`ignore` (arg name lists), `isolate` (runs in a unique tempdir under `$XDG_CACHE_HOME/fleche/cwd/` — **not thread-safe**, uses `os.chdir`). Plus per-argument markers `Ignored[T]` / `Required[T]` via `__class_getitem__` → `Annotated`. Bump `version=` to invalidate without changing code.

### Storage hierarchy

```
Cache
├── values: ValueStorage  → ValueMemory | ValuePickleFile | ValueBagOfHoldingH5File | ValueVoid
└── calls:  CallStorage   → CallMemory  | CallPickleFile  | CallBagOfHoldingH5File  | CallVoid | Sql
```

### Config

See `config.py` module docstring for the authoritative type-string reference and a worked TOML example. Two API layers, both live in `config.py`:

- `cache_from_config(d)` (programmatic): shape-dispatches — list → `CacheStack`; dict with `max_size` → `SizeLimitedCache`; dict with `read_only: true` → wraps in `ReadOnlyCache`; else `Cache`.
- `load_cache_config(name)` (TOML loader, called at import time from `state.py`): only ever produces a plain `Cache` via `_create_cache` — `max_size`/`read_only`/list-stack keys in TOML are silently ignored. Wire those up programmatically. Special named caches `"memory"` and `"void"` bypass the config file. `metadata = [...]` only accepts `"Runtime"` — `"Tags"` raises (it requires arguments).

### Security (optional)

Pickle-family backends accept `secret_key` (list of hex strings) or fall back to `FLECHE_SECRET_KEY` env var (colon-separated hex). `SignedBytes` in `security.py` signs payloads with HMAC-SHA256; hex encoding avoids the pickle STOP opcode so the signature can be split off on load by `rfind(pickle.STOP)`. Supports key rotation (first key signs, all keys verify). `SignatureError` from `SignedBytes.loads` is caught in `PickleFileBackend._from_file` and re-raised as `KeyError`, so tampered entries behave as missing rather than hard-failing.

## Test layout

`tests/` has `conftest.py` (registers `tests.fixtures` as a pytest plugin), `fixtures.py` (shared fixtures), `strategies.py` (hypothesis strategies), and three subtrees:

- `unit/` — one subdirectory per module under test (`caches/`, `call/`, `config/`, `digest/`, `fleche/`, `metadata/`, `storage/`); filenames mirror the feature being tested. Two top-level files: `test_cache_sticky.py` (sticky `cache()` context semantics) and `test_pickle.py` (pickling caches/wrappers).
- `integration/` — `test_integration.py` (main), `test_notebooks.py` (exercises `notebooks/`), `test_parallel_execution.py`, `test_methods.py`, `test_wrapper_query_integration.py`, `test_hash_code_integration.py`.
- `regression/` — `test_issue_{297,319,352}.py`, `test_sql_concurrent_save.py`, `test_sql_table_uniqueness.py`.

## Other directories

- `benchmarks/` — `benchmark_{digest,integration,storage}.py`, `run_benchmarks.py`, `utils.py`, `results.csv`.
- `devnotes/storage-hierarchy.{dot,md,svg}` — rendered inheritance diagram for the storage classes.
- `docs/` — Sphinx sources (`*.rst` per topic: `cache_stack`, `configuration`, `custom_digests`, `digests_as_args`, `helpers`, `lazy_call`, `parallel_execution`, `query`, `security`, `installation`).
- `notebooks/` — usage examples (`GettingStarted`, `Caches`, `CacheStack`, `StorageBackends`, `SecureStorage`, `ConcurrentExecution`, `ExtraMethods`, `TransferWorkflow`); exercised by `tests/integration/test_notebooks.py`.
- `.github/workflows/` — CI: `tests.yml`, `ty.yml`, `benchmarks.yml`/`updatebenchmarks.yml`, `rendernb.yml`, `pypi-publish.yml`.

## PR and Issue notes

If tasked to work in a 'separate issue/PR' keep your detailed response there and only add a quick link to the original
issue or PR.

# General Instructions

When you cannot complete a task or question because you are missing depedencies fail early and report the errors.

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
