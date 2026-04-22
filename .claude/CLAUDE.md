# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Quick Reference

**What:** Persistent function cache (`@fleche()` decorator) — like `lru_cache` but survives restarts. SHA256 content-based keys, pluggable backends. Values and calls are stored separately so call records are queryable without deserializing heavy values.

**Entry points:** `wrapper.py` (decorator) → `call.py` (`Call.to_lookup_key`) → `digest.py` (SHA256) → `caches.py` (cache objects) → `storage/` (backends).

**Active cache:** `ContextVar` in `state.py`. Switched via `with cache(my_cache):`, or *stickily* if you discard the returned context manager (cache stays until scope exit or another `set`). Default loaded from `./fleche.toml`, `$XDG_CONFIG_HOME/fleche/cache.toml`, or `~/.fleche.toml`.

**Backends (config `type` strings):** `"memory"`, `"void"`, `"pickle"` / `"cloudpickle"` / `"dill"` (filesystem with chosen serializer), `"bagofholding_hdf"` (HDF5), `"sql"` (SQLAlchemy, **calls only**). All non-stdlib backends import via `pyiron_snippets.ImportAlarm` — absent extras raise on first use only.

**Key files (`src/fleche/`):**
| File | Role & non-obvious bits |
|------|-------------------------|
| `__init__.py` | Exports `fleche`, `cache`, `meta`, `tags`, `project`, `BoundWrapper`, `Ignored`, `Required`, `D`. `D(x)` returns the short-prefix digest verbatim if `x` looks like hex and ≤`DIGEST_LENGTH`; otherwise computes `digest(x)`. |
| `wrapper.py` | `@fleche()` decorator. Decorator kwargs: `version`, `meta`, `hash_version`, `hash_module`, `hash_code`, `require`/`ignore`, `isolate`. Attaches `.call/.digest/.load/.contains/.query/.rerun` helpers (also under `.fleche` namespace; original fn at `.__wrapped__`). `Ignored[T]` / `Required[T]` annotations via `__class_getitem__` → `Annotated`. **`None` results are not cached** (logs a warning). **`isolate=True` uses `os.chdir` — not thread-safe**; workdirs go under `$XDG_CACHE_HOME/fleche/cwd/`. Positional/kw `Digest` args are auto-expanded to their cached values before hashing. |
| `call.py` | `Call` dataclass (+ `LazyCall` for deferred value load, `QueryCall` with `None`-wildcards). `Call.to_lookup_key()` drops `metadata`/`result`, preserves arg order. `bind(func, args, kwargs, apply_defaults, partial)` wraps `inspect.Signature.bind`. |
| `digest.py` | `Digest(str)` subclass; `digest()` returns a `Digest`. Handles str/bytes/int/Number/NaN/bool/None/dict/np.ndarray/FunctionType/CodeType/dataclass/Iterable natively. Objects can define `__digest__`. Third-party types extend via `add_hook((type, fn))` or the `fleche` entry-point group — re-attempted lazily on `Unhashable`. |
| `caches.py` | `BaseCache` (ABC) → `Cache` (values+calls), `CacheStack` (save hits bottom, load traverses up and auto-promotes hits from higher caches), `ReadOnlyCache`, `FilteredCache` (wraps `ReadOnlyCache` w/ predicate or `QueryCall`), `RefreshingCache` (forces recompute, used by `.rerun`), `SizeLimitedMixin` + `SizeLimitedCache` (random eviction; override `_pick_eviction_target`). `Cache.transfer()` moves calls between caches. `Cache.redigest()` re-keys after digest semantics change. |
| `state.py` | `cache()`/`meta()`/`tags()`/`project()` context managers; all are sticky (see above). `BoundWrapper.bind(fn)` freezes current cache+metadata into a picklable callable — used to ship wrapped functions to `ProcessPoolExecutor` etc. **`BoundWrapper` is a plain callable without the `.fleche` helper namespace**; access helpers via `bound.func.fleche.*`. |
| `query.py` | `QueryIterator` with `only/any/count/empty/take/skip/filter/sorted/unique/groupby/latest/oldest/evict/results/table`. `.table()` flattens metadata → columns; `timestart`/`timestop` auto-converted to local tz; argument-name clashes prefixed `a_`. `latest`/`oldest` require `Runtime` metadata. |
| `metadata.py` | `MetaData` ABC (`pre(call) -> dict`, `post(pre, call) -> dict`, `name`, `keys`). Values must be JSON-serializable. Built-ins: `Runtime` (`timestart`/`timestop`/`walltime`), `Tags` (arbitrary kv). |
| `config.py` | TOML loader; canonical type-string reference in module docstring. `cache_from_config`/`cache_to_config`/`storage_from_config`/`storage_to_config` for round-tripping. Named caches cached in `_live_caches`; special names `"memory"`/`"void"` return transient caches without touching the config file. |
| `security.py` | `SignedBytes` HMAC-SHA256 wrapper (hex-encoded so it can't contain pickle STOP). `FLECHE_SECRET_KEY` env var / per-backend `secret_key`. Key rotation: first key signs, all verify. **In pickle backends a failed signature raises `KeyError`** (treated as a cache miss rather than a hard failure). |

### `storage/`

```
KeyManagement (list/_evict/_contains/expand/shrink, _operation_context)
 └── StorageBackend (put/get)
      ├── ValueStorage  ── ValueMixin   ─┐  save/load on top of put/get
      └── CallStorage   ── CallMixin    ─┘  (CallStorage also defines transform())
```

Concrete classes (all `@dataclass(frozen=True)`; mixin fields merge via MRO — **do not pass `init=False`**):
- `ValueMemory(ValueMixin, DestructuringMixin, MemoryBackend)`, `CallMemory(CallMixin, MemoryBackend)` — no destructuring for calls
- `ValueVoid(ValueMixin, VoidBackend)`, `CallVoid(CallMixin, VoidBackend)` — discard everything
- `ValuePickleFile(PerKeyLockMixin, ValueMixin, DestructuringMixin, PickleFileBackend)`, `CallPickleFile(PerKeyLockMixin, CallMixin, PickleFileBackend)` — use `.with_pickle()`/`.with_cloudpickle()`/`.with_dill()` classmethods to pick serializer
- `ValueBagOfHoldingH5File` / `CallBagOfHoldingH5File` — same composition with `BagOfHoldingH5FileBackend`
- `Sql(PerKeyLockMixin, CallStorage)` — **bypasses `CallMixin`**; implements `put`/`get`/`save`/`load`/`query`/`expand` directly against SQLAlchemy (thread-local session, SQL-side arg/metadata filtering for simple types with client-side fallback)

Other storage modules:
- `base.py` — `AmbiguousDigestError`, `SaveError`, `_resolve_prefix` helper
- `file.py` — `FileStorage` (root dir, `file_write_lock`/`file_read_lock` helpers, exponential backoff)
- `destructuring.py` — `DestructuringMixin` (`remaining_depth` field; recursive sundering/mending), markers `DigestedIterable`/`DigestedDict` (re-exported from `caches` for BC), `count_reuses()` for shared sub-values
- `thread_safe.py` — `SerializingMixin` (single global RLock) vs `PerKeyLockMixin` (weakref per-key RLock table, reentrant). Both picklable; lock state resets on unpickle (**not inter-process**).
- Every op enters `_operation_context(key)`; mixins chain via `super()._operation_context` so you can stack locks/sessions.

---

## Commands

```bash
pip install -e ".[tests]"                          # install with test deps
pytest tests/                                      # all tests
pytest tests/unit/digest/test_digest.py::test_name # single test
ty check src/                                      # type check (CI)
python -m benchmarks.run_benchmarks                # benchmarks
```

Optional extras: `[cloudpickle]`, `[dill]`, `[sqlalchemy]`, `[bagofholding]`, `[executorlib]`, `[docs]`.

## Test layout

```
tests/
├── unit/
│   ├── test_cache_sticky.py, test_pickle.py  # top-level unit tests
│   ├── caches/    # cache, cache_stack, filter, readonly_cache, size_limited,
│   │             # lazy_call, redigest, expand_shrink
│   ├── call/      # partial_binding, code_digest, matches
│   ├── config/    # config, cache_from_config, cache_to_config, storage_to_config
│   ├── digest/    # digest, entry_points
│   ├── fleche/    # fleche, bound_wrapper, dataclass_input, decorator_attributes,
│   │             # digest_args, futures, hash_code, ignore_digest, process_args,
│   │             # processpool, query_iterator, rerun, signature_binding,
│   │             # type_hints, workdir
│   ├── metadata/
│   └── storage/   # storage, file_storage, pickle_file, bagofholding_file,
│                  # sql_digest_types / sql_query / sql_url_coercion,
│                  # destructuring_storage, thread_safe, secure_storage, void,
│                  # short_digest, operation_context, optional_deps, overwrite,
│                  # transform
├── integration/   # integration, methods, notebooks, parallel_execution,
│                  # wrapper_query_integration, hash_code_integration
├── regression/    # issue_297, issue_319, issue_352,
│                  # sql_concurrent_save, sql_table_uniqueness
├── fixtures.py    # shared pytest fixtures
├── conftest.py
└── strategies.py  # hypothesis strategies
```

## PR and Issue notes

If tasked to work in a 'separate issue/PR' keep your detailed response there and only add a quick link to the original
issue or PR.

# General Instructions

When you cannot complete a task or question because you are missing depedencies fail early and report the errors.
