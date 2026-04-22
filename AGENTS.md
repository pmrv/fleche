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
| `digest.py` | `Digest(str)` (with `.expand`/`.shrink`); `digest()` (SHA256 hex); `Hook`, `add_hook`, `get_hooks`; `Unhashable`; `DIGEST_LENGTH=64`; entry-point hooks for numpy/complex/etc. |
| `call.py` | `Call` dataclass (`from_call`, `to_lookup_key`); `LazyCall` (deferred deser via `_cache`); `QueryCall` (wildcard match via `matches`); `bind()` wrapper over `inspect.Signature.bind[_partial]` |
| `caches.py` | `BaseCache`, `Cache`, `CacheStack`, `ReadOnlyCache`, `FilteredCache`, `RefreshingCache`, `SizeLimitedMixin`/`SizeLimitedCache`; `Rejected` exception; `Cache.transfer`, `.readonly`, `.push`, `.filter`, `.table`, `.redigest` |
| `state.py` | `cache()`, `meta()`, `tags()`, `project()`; `_StickyContext` (backport of Py3.14 Token CM); `BoundWrapper` (freezes cache + metadata for pickling) |
| `query.py` | `QueryIterator` — lazy helpers: `only/any/count/empty/take/skip/filter/sorted/unique/groupby/latest/oldest/evict/results/table`; `.table()` → pandas DataFrame (auto-converts `timestart`/`timestop` to local tz) |
| `metadata.py` | `MetaData` ABC (`pre`/`post` → JSON-serializable); built-ins `Runtime` (timestart/timestop/walltime), `Tags` |
| `config.py` | TOML loader; `storage_from_config`/`storage_to_config`, `cache_from_config`/`cache_to_config` (round-trippable); `_live_caches` interns named caches. See module docstring for full type reference. |
| `security.py` | `SignedBytes` HMAC-SHA256 wrapper (hex-encoded so it never contains pickle STOP); `SignatureError`; `normalize_secret_key`/`get_secret_key`; `FLECHE_SECRET_KEY` env var / `secret_key` config key |
| `executor.py` | `wrap_executor(executor)` monkey-patches `.submit`: cached fleche calls skip the executor and return a pre-completed `Future`; misses are auto-`bind()`'d so cache/metadata context reaches the worker. Splits off executor-reserved kw-only params (e.g. `resources=`) from payload kwargs. Idempotent. |

**Storage layout (`storage/`):**
- `base.py` — `KeyManagement` (`list`/`_evict`/`_contains` abstract; `evict`/`contains`/`expand`/`shrink`/`_normalize_key` concrete; `_operation_context` hook) → `StorageBackend` (adds `put`/`get`) → domain ABCs `ValueStorage`/`CallStorage` (+ `transform`) → **bridge mixins** `ValueMixin`/`CallMixin` that implement `save`/`load`[/`query`] on top of `put`/`get`. Also: `SaveError`, `AmbiguousDigestError`, `_resolve_prefix`.
- `file.py` — `FileStorage` base for disk-backed backends: locking (`file_write_lock`/`file_read_lock` with exponential backoff), `root` resolution, `_to_file`/`_from_file` hooks. Compression and signing live in `pickle_file.py`, not here.
- `memory.py`, `void.py`, `pickle_file.py` (+`PickleFileBackend.with_pickle`/`with_cloudpickle`/`with_dill`), `bagofholding_file.py`, `sql.py` — concrete backends (each exposes `Value*` and/or `Call*` classes; `sql.py` only has `Sql` for calls).
- `destructuring.py` — `DestructuringMixin` for recursive value splitting + `DigestedIterable`/`DigestedDict`/`Digested` markers (preserve digest equivalence via `__digest__`). `remaining_depth` (default `0`) controls how deep structures are split across keys.
- `thread_safe.py` — `SerializingMixin` (single RLock), `PerKeyLockMixin` (striped locks via a module-level `WeakKeyDictionary`); `_PicklableLock`/`_PicklableRLock` (survive pickle round-trip, state not preserved).

**Storage class composition:** Concrete classes are `@dataclass(frozen=True)` and inherit via MRO. Thread-safety mixins are **already baked into** the disk-backed classes — do not wrap them again:
- `ValueMemory(ValueMixin, DestructuringMixin, MemoryBackend)`
- `CallMemory(CallMixin, MemoryBackend)`
- `ValuePickleFile(PerKeyLockMixin, ValueMixin, DestructuringMixin, PickleFileBackend)`
- `CallPickleFile(PerKeyLockMixin, CallMixin, PickleFileBackend)`
- `ValueBagOfHoldingH5File`/`CallBagOfHoldingH5File` — same pattern (PerKeyLock + …Mixin + [Destructuring] + BagOfHoldingH5FileBackend)
- `Sql(PerKeyLockMixin, CallStorage)` — bespoke; bypasses `StorageBackend`/`CallMixin`, implements `put`/`get`/`query` directly against SQLAlchemy; `__reduce__` reconstructs from `(url, echo)`

Each mixin/backend declares its own dataclass fields; Python's dataclass machinery merges them into one generated `__init__` via MRO — **do not pass `init=False`** on user-facing fields. Internal state (locks, `_keys` on `SizeLimitedMixin`, `engine`/`session` on `Sql`) uses `field(init=False, repr=False, compare=False)` and is rebuilt in `__post_init__` via `object.__setattr__`.

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

Optional deps are gated via `pyiron_snippets.import_alarm.ImportAlarm` — importing a backend without its extra installed raises at construction, not import.

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

See `config.py` module docstring for the authoritative type-string reference. `cache_from_config` shape-dispatches: list → `CacheStack`; dict with `max_size` → `SizeLimitedCache`; dict with `read_only: true` → wraps in `ReadOnlyCache`; else `Cache`. Special named caches `"memory"` and `"void"` bypass the config file. Example `fleche.toml`:
```toml
[default]
cache = "persistent"
metadata = ["Runtime"]            # "Tags" is NOT allowed here

[persistent]
values.type = "cloudpickle"
values.root = "~/.fleche/values"
calls.type  = "cloudpickle"
calls.root  = "~/.fleche/calls"
```

### Security (optional)

Pickle-family backends accept `secret_key` (list of hex strings) or fall back to `FLECHE_SECRET_KEY` env var (colon-separated hex). `SignedBytes` in `security.py` signs payloads with HMAC-SHA256; hex encoding avoids the pickle STOP opcode so the signature can be split off on load. Supports key rotation (first key signs, all keys verify). `SignatureError` from `SignedBytes.loads` is caught in `PickleFileBackend._from_file` and re-raised as `KeyError`, so tampered entries behave as missing rather than hard-failing.

## Test layout

```
tests/
├── conftest.py     # registers tests.fixtures as a pytest plugin
├── fixtures.py     # shared pytest fixtures
├── strategies.py   # hypothesis strategies
├── unit/
│   ├── caches/      # cache/stack/filter/readonly/size_limited/lazy_call/redigest/expand_shrink
│   ├── call/        # partial_binding, code_digest, matches
│   ├── config/      # config, cache_from_config, cache_to_config, storage_to_config
│   ├── digest/      # digest, entry_points
│   ├── fleche/      # fleche (decorator), bound_wrapper, dataclass_input, decorator_attributes,
│   │                # digest_args, futures, hash_code, ignore_digest, process_args, processpool,
│   │                # query_iterator, rerun, signature_binding, type_hints, workdir
│   ├── metadata/    # test_metadata
│   ├── storage/     # storage, file_storage, mixins, pickle_file, bagofholding_file, sql_query,
│   │                # sql_digest_types, sql_url_coercion, destructuring_storage, thread_safe,
│   │                # secure_storage, void, short_digest, operation_context, optional_deps,
│   │                # overwrite, transform
│   ├── test_cache_sticky.py   # top-level: sticky cache context semantics
│   └── test_pickle.py         # top-level: pickling of caches/wrappers
├── integration/    # integration (main), notebooks, parallel_execution, methods,
│                   # wrapper_query_integration, hash_code_integration
└── regression/     # test_issue_{297,319,352}, test_sql_concurrent_save, test_sql_table_uniqueness
```

## Other directories

- `benchmarks/` — `benchmark_{digest,integration,storage}.py`, `run_benchmarks.py`, `utils.py`, `results.csv`.
- `devnotes/storage-hierarchy.{dot,md,svg}` — rendered inheritance diagram for the storage classes.
- `notebooks/` — usage examples (exercised by `tests/integration/test_notebooks.py`).

## PR and Issue notes

If tasked to work in a 'separate issue/PR' keep your detailed response there and only add a quick link to the original
issue or PR.

# General Instructions

When you cannot complete a task or question because you are missing depedencies fail early and report the errors.
