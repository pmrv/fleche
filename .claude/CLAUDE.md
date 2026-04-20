# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Quick Reference

**What:** Persistent function cache (`@fleche()` decorator) — like `lru_cache` but survives restarts. SHA256 content-based keys, pluggable backends.

**Entry points:** `wrapper.py` (decorator) → `call.py` (key building) → `digest.py` (hashing) → `caches.py` (cache objects) → `storage/` (backends)

**Active cache:** `ContextVar` in `state.py`; switch with `with cache(my_cache):`. Config auto-loaded from `./fleche.toml`, `$XDG_CONFIG_HOME/fleche/cache.toml`, or `~/.fleche.toml` by `config.py`.

**Backends (config `type` strings):** `"memory"`, `"void"`, `"pickle"` / `"cloudpickle"` / `"dill"` (filesystem with chosen serializer), `"bagofholding_hdf"` (HDF5), `"sql"` (SQLAlchemy, **calls only**). Values and calls are stored separately so call records are queryable without deserializing heavy values.

**Key files:**
| File | Role |
|------|------|
| `wrapper.py` | `@fleche()` decorator; `Ignored`/`Required` arg markers; attaches `.call/.digest/.load/.contains/.query/.rerun` helpers |
| `digest.py` | `Digest(str)` + `digest()` function; SHA256 over arbitrary objects; pluggable hooks for numpy/complex/etc. |
| `call.py` | `Call` dataclass; `LazyCall` (deferred deser), `QueryCall` (wildcard match) |
| `caches.py` | `BaseCache`, `Cache`, `CacheStack`, `ReadOnlyCache`, `FilteredCache`, `RefreshingCache`, `SizeLimitedCache` |
| `state.py` | `cache()`, `meta()`, `tags()`, `project()` context managers; `BoundWrapper` |
| `query.py` | `QueryIterator.table()` → pandas DataFrame; `.results()` for values |
| `metadata.py` | `MetaData` ABC (`pre`/`post`); built-ins `Runtime`, `Tags` |
| `config.py` | TOML loader; resolves named caches; see docstring for full type reference |
| `security.py` | `SignedBytes` HMAC-SHA256 wrapper for pickle backends; `FLECHE_SECRET_KEY` env var / `secret_key` config key |

**Storage layout (`storage/`):**
- `base.py` — `KeyManagement` (list/_evict/_contains/expand/shrink) → `StorageBackend` (adds `put`/`get`) → domain ABCs `ValueStorage`/`CallStorage` (`save`/`load`[/`query`]) → **bridge mixins** `ValueMixin`/`CallMixin` that implement `save`/`load` on top of `put`/`get`
- `memory.py`, `void.py`, `pickle_file.py`, `bagofholding_file.py`, `sql.py` — concrete backends (each exposes `Value*` and/or `Call*` classes; `sql.py` only has `Sql` for calls)
- `file.py` — shared `FileStorage` base for disk-backed backends (locking, root dir, compress)
- `destructuring.py` — `DestructuringMixin` for recursive value splitting + `DigestedIterable`/`DigestedDict` markers
- `thread_safe.py` — `SerializingMixin`, `PerKeyLockMixin` (wrap backends via `_operation_context`)

**Storage class composition:** Concrete classes like `ValueMemory(ValueMixin, DestructuringMixin, MemoryBackend)` are `@dataclass(frozen=True)`. Each mixin/backend declares its own fields; Python's dataclass machinery merges them into one generated `__init__` via MRO — **do not pass `init=False`**.

---

## Commands

```bash
pip install -e ".[tests]"                              # install with test deps
pytest tests/                                          # all tests
pytest tests/unit/digest/test_digest.py::test_name     # single test
ty check src/                                          # type check
python -m benchmarks.run_benchmarks                    # benchmarks
```

Lint: flake8, `max-line-length=120` (`.flake8`).

## Architecture notes

### Core data flow

1. `@fleche()` wraps a function.
2. On call: args/kwargs → `Call.from_call()` → `.to_lookup_key()` → `digest()` (SHA256 hex).
3. Hit → return stored result. Miss → execute, run post-hooks (metadata), save `Call` + result.
4. Active cache is a `ContextVar` — thread-safe, switchable via `with cache(my_cache):`.

### Cache key control

Decorator kwargs (`wrapper.py`): `version`, `meta`, `hash_version`, `hash_module`, `hash_code` (hashes function source), `require`/`ignore` (arg name lists), `isolate`. Plus per-argument markers `Ignored[T]` / `Required[T]` via `__class_getitem__`. Bump `version=` to invalidate without changing code.

### Storage hierarchy

```
Cache
├── values: ValueStorage  → ValueMemory | ValuePickleFile | ValueBagOfHoldingH5File | ValueVoid
└── calls:  CallStorage   → CallMemory  | CallPickleFile  | CallBagOfHoldingH5File  | CallVoid | Sql
```

### Config

See `config.py` module docstring for the authoritative type-string reference. Example `fleche.toml`:
```toml
[default]
cache = "persistent"
metadata = ["Runtime"]

[persistent]
values.type = "cloudpickle"
values.root = "~/.fleche/values"
calls.type  = "cloudpickle"
calls.root  = "~/.fleche/calls"
```

### Security (optional)

Pickle-family backends accept `secret_key` (list of hex strings) or fall back to `FLECHE_SECRET_KEY` env var (colon-separated hex). `SignedBytes` in `security.py` signs payloads with HMAC-SHA256; hex encoding avoids the pickle STOP opcode. Supports key rotation (first key signs, all keys verify).

## Test layout

```
tests/
├── unit/
│   ├── caches/      # cache/stack/filter/readonly/size_limited/lazy_call/redigest/expand_shrink
│   ├── call/        # partial binding, code digest, matches
│   ├── config/
│   ├── digest/
│   ├── fleche/      # decorator, hash_code, ignore/required, processpool, rerun, bound_wrapper, ...
│   ├── metadata/
│   └── storage/     # pickle_file, bagofholding_file, sql_*, destructuring, thread_safe, secure, void, short_digest, operation_context, optional_deps, overwrite, transform
├── integration/     # notebooks, parallel execution, methods, wrapper+query, hash_code
├── regression/      # test_issue_297, test_issue_319, test_sql_concurrent_save, test_sql_table_uniqueness
├── fixtures.py      # shared pytest fixtures
└── strategies.py    # hypothesis strategies
```

## PR and Issue notes

If tasked to work in a 'separate issue/PR' keep your detailed response there and only add a quick link to the original
issue or PR.

# General Instructions

When you cannot complete a task or question because you are missing depedencies fail early and report the errors.
