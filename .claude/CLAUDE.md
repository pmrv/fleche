# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What is fleche?

A persistent caching library for Python functions — like `lru_cache` but persisted across runs. The `@fleche()` decorator wraps functions, generates content-based cache keys via SHA256 hashing, and stores results in configurable backends (file, SQL, memory, HDF5).

## Commands

```bash
# Install with test dependencies
pip install -e ".[tests]"

# Run all tests
pytest tests/

# Run a single test file
pytest tests/unit/digest/test_digest.py

# Run a single test
pytest tests/unit/digest/test_digest.py::test_name

# Type checking
ty check src/

# Run benchmarks
python -m benchmarks.run_benchmarks
```

Linting: flake8 with max-line-length=120 (see `.flake8`).

## Architecture

### Core data flow

1. `@fleche()` wraps a function
2. On call: args/kwargs → `Call.from_call()` → `.to_lookup_key()` → `digest.digest()` (SHA256 hex string)
3. Cache hit → return stored result; cache miss → execute, collect metadata, store `Call` + result
4. Active cache is a context variable in `state.py` — thread-safe, switchable via `with cache(my_cache):`

### Key modules

- **`wrapper.py`** — `fleche()` decorator; attaches helpers (`.call()`, `.digest()`, `.load()`, `.contains()`, `.query()`, `.rerun()`) to the wrapped function; handles `Ignored`/`Required` argument markers and versioning
- **`digest.py`** — `Digest` (subclass of `str`) and `digest()` function; SHA256 over arbitrary Python objects; extensible hook system for custom types; handles numpy, pandas, complex numbers
- **`call.py`** — `Call` dataclass holding function name, arguments dict, metadata, module/version/code_digest; `LazyCall` for deferred deserialization; `QueryCall` for wildcard searches
- **`caches.py`** — `BaseCache` abstract base; `Cache` (main, wraps value + call storage); `CacheStack` (layered hierarchy); `ReadOnlyCache`, `FilteredCache`, `RefreshingCache`
- **`storage/`** — Backend implementations all implement `save/load/_contains/list/expand/shrink`: `memory.py` (dict), `void.py` (no-op), `pickle_file.py` (filesystem), `sql.py` (SQLAlchemy), `bagofholding_file.py` (HDF5)
- **`state.py`** — `ContextVar`-based global state; `cache()`, `meta()`, `tags()`, `project()` context managers
- **`config.py`** — TOML config loader; looks for `fleche.toml` (local) or `~/.fleche.toml` (XDG global); defines named caches and metadata defaults
- **`metadata.py`** — Pre/post execution hooks producing JSON-serializable values; built-ins: `Runtime`, `Tags`
- **`query.py`** — `QueryIterator` with `.table()` → pandas DataFrame

### Storage hierarchy

```
Cache
├── values: DestructuringStorage → (Memory | PickleFile | BagOfHoldingH5File | Sql | Void)
└── calls: CallStorageAdapter   → (same backends)
```

Values and calls are stored separately so metadata/call records can be queried without deserializing heavy results.

### Cache key control

The `@fleche()` decorator accepts flags to include/exclude from the hash: `hash_version`, `hash_module`, `hash_code` (hashes the function source), plus per-argument `Ignored`/`Required` wrappers. This lets users invalidate caches by bumping a version number without changing code.

### Configuration

`fleche.toml` example:
```toml
[default]
cache = "mycache"
metadata = ["Runtime"]

[mycache]
values.type = "CloudpickleFile"
values.root = ".fleche/values"
calls.type = "CloudpickleFile"
calls.root = ".fleche/calls"
```

## Test layout

```
tests/
├── unit/          # Per-module unit tests (digest/, call/, caches/, storage/, ...)
├── integration/   # Cross-module tests (notebooks, SQL constraints, threading, executors)
├── fixtures.py    # Shared pytest fixtures
└── strategies.py  # Hypothesis strategies
```

## PR and Issue notes

If tasked to work in a 'separate issue/PR' keep your detailed response there and only add a quick link to the original
issue or PR.
