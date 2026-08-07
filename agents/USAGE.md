# USAGE.md

> **AI-agent reference.** This file is written for AI coding agents (Codex,
> Cursor, Aider, Claude, ...) working in or against this repo, linked from
> [AGENTS.md](../AGENTS.md) — not human-facing documentation.

How to use the `fleche` library as a dependency — decorating functions,
configuring caches, choosing storage backends, querying results. If you're
modifying fleche's own source instead, see [DEVELOPING.md](DEVELOPING.md).

This is the condensed, agent-oriented version. Full human docs live in
`docs/` (Sphinx sources — read the `.rst` files directly, or build with
Sphinx) and runnable notebooks in `notebooks/`; this file links to the
authoritative source for anything it summarizes.

## Basic usage

```python
from fleche import fleche

@fleche()
def expensive(x, y):
    ...  # only re-runs when x, y, or the function's code change
```

- The decorator digests the function's identity (qualified name, module,
  `version`, and optionally `func.__code__` when `hash_code=True`) together
  with its arguments (SHA256, content-based — not `id()`/pickle-identity
  based) into a lookup key, and returns the stored result on a hit.
- Helpers attached to the wrapped function: `.call`, `.digest`, `.load`,
  `.contains`, `.query`, `.rerun`, `.bind` (mirrored under `.fleche.*` too).
- Returning `None` is never cached (a warning is logged) — fleche can't
  distinguish "cached `None`" from "no result yet".

## The active cache

There is exactly one *active* cache at a time (a thread-safe `ContextVar`),
used by every `@fleche()`-wrapped function that doesn't specify otherwise.

```python
from fleche import cache

cache("mycache")            # sticky: switches the active cache and stays switched
with cache("mycache"):      # scoped: active only inside the `with` block
    ...
cache()                      # returns the current active cache, doesn't change it
```

Two reserved names bypass config entirely:
- `cache("memory")` — a process-lifetime in-memory cache (not shared across
  processes, not persisted to disk).
- `cache("void")` — discards everything; use to disable caching without
  touching decorated code.

`cache("default")` / `cache()` with no config resolves to whatever
`[default]` names in `fleche.toml` (see below), or a plain in-memory cache
if no config file is found anywhere.

## Config files — where fleche looks, and what's in them

**This is the part that's easy to get wrong, so read it before writing a
`fleche.toml`.**

Fleche looks for **`fleche.toml`** files — there is no single fixed path.
On the first cache/metadata lookup it:

1. Walks from the **current working directory upward** to `$HOME`
   (inclusive) or the filesystem root, collecting every `fleche.toml` it
   passes.
2. Appends `$XDG_CONFIG_HOME/fleche/cache.toml` (or
   `~/.config/fleche/cache.toml` if that env var is unset/empty) as a
   final, lowest-priority layer.
3. **Shallow-merges** all discovered files at the top level: a file closer
   to the CWD wins outright, and its top-level table *replaces* (not
   recursively merges into) the same-named table from a farther file.

So a project-local `./fleche.toml` overrides `~/fleche.toml`, which
overrides the XDG fallback. If no file is found anywhere, fleche silently
falls back to an in-memory-only cache — no error is raised.

A relative `root`/`url` inside a `fleche.toml` resolves against **the
directory containing that file**, not the CWD the process happens to run
from — so the same config file resolves to the same cache location
regardless of which subdirectory the walk found it from. Absolute and
`~`-prefixed paths are unaffected.

To stop that upward inheritance, set `root = true` in a file's `[default]`
table. The walk halts at the closest `root` file: files farther up the tree
(and the XDG fallback) are ignored, so only that file and any closer to the
CWD contribute. This is the ESLint `root: true` pattern — pin a project's
config without inheriting whatever `fleche.toml` lives in a parent directory
or `$HOME`.

A minimal file:

```toml
[default]
cache = "persistent"        # which section below is "the" default cache
metadata = ["Runtime"]      # this is the default even if the key is omitted

[persistent]
values.type = "cloudpickle"
values.root = "~/.cache/fleche/values"
calls.type = "cloudpickle"
calls.root = "~/.cache/fleche/calls"
```

For the common cases a section can instead name a `template` plus its
required storage args — `template = "cloudpickle"` with a single `root`
splits into `root/values` + `root/calls`; `memory`/`pickle`/`dill`/
`bagofholding_hdf` work the same way. `template = "sql"` stores values under
`root/values` (backend `values`, default `bagofholding_hdf`) and calls in SQL
at `url` (default `sqlite:///root/calls.db`, overridable). In Python, build a
cache from the same dict with `Cache.from_config({...})` (the
`BaseCache.from_config` classmethod, a thin wrapper over
`config.cache_from_config`) and pass it to `cache(...)`. Anything a template
doesn't cover (mixed backends, per-backend options) falls back to the explicit
`values`/`calls` form below.

Every cache section (`[persistent]` above) needs a `values` backend
(stores function results) and a `calls` backend (stores call
metadata/arguments) — see the backend table below for `type` options.
A section can add `read_only = true` (wraps it in a `ReadOnlyCache` — loads
still work, saves/evicts raise `Rejected`) or `max_size = N` (a
`SizeLimitedCache` — evicts uniformly at random by default; override
`_pick_eviction_target` for LRU/LFU/etc.). A TOML array-of-tables (`[[name]]`)
builds a `CacheStack` (fast layer in front of a persistent one; reads fall
through and back-fill hits). `[[name.pool]]` builds a read-only
`CachePool` (fans reads out over several caches, never writes to any of
them — e.g. to read from a teammate's cache alongside your own).

Full worked examples for every shape (stack, pool, read-only, size-limited,
SSH-remote) are in `docs/storage/configuration.rst` and the module
docstring of `src/fleche/config.py` — copy from there rather than
re-deriving the TOML by hand.

## Choosing a storage backend (the `type` key)

| `type` | Backend | Required keys | Notes |
|---|---|---|---|
| `"memory"` | in-process dict | — | lost on process exit |
| `"void"` | no-op | — | discards everything |
| `"pickle"` / `"cloudpickle"` / `"dill"` | filesystem, one file per entry | `root` | `cloudpickle`/`dill` handle lambdas/closures stdlib `pickle` can't; optional `compress`, `secret_key` (HMAC signing) |
| `"bagofholding_hdf"` | HDF5 file(s) via `bagofholding` | `root` | optional `version_validator`, `prefix_length` (multiplex keys sharing an N-char digest prefix into one shared `.h5` file instead of one file per key; default `2`, `0` for one file per key, `None` infers from existing files; validated against existing files in `root` at construction — `refix(n)` migrates and returns the re-sharded storage, the `consolidate(root, n)` classmethod repairs a mixed root) |
| `"sql"` | SQLAlchemy | `url` | **calls only** — pair with a value backend above |
| `"ssh"` | forwards to a remote `python -m fleche remote --serve` process | `host` | whole-cache forwarding, not a per-key backend |

`values` and `calls` are stored separately on purpose: call records
(arguments, metadata) are queryable without deserializing the
(potentially heavy) result values.

## Controlling the cache key

Decorator kwargs on `@fleche(...)`:

- `version=` — bump to invalidate old entries without changing code.
- `ignore=[...]` / `require=[...]` — argument names to exclude from the
  key, or to force present (a call missing a `require`d kwarg runs
  uncached, with a warning).
- `hash_code=True` — folds `func.__code__` into the key (invalidates on
  any code edit).
- `hash_version=` / `hash_module=` — pin the digest scheme / module
  identity explicitly.
- `meta=[...]` — metadata classes to record (`Runtime`, `Environment`,
  `Git`, or a `Tags(...)` instance) — see `docs/usage/`.
- `isolate=True` — runs each call in a unique tempdir (not thread-safe;
  uses `os.chdir`).
- Per-argument: `Ignored[T]` / `Required[T]` type annotations do the same
  thing as `ignore=`/`require=`, inline in the signature.

## Digesting third-party / custom types

Three mechanisms, in precedence order (highest first):

1. `fleche.digest.add_hook((MyType, digest_fn))` — manual registration,
   overrides everything else for that type.
2. **Entry points** — installed packages register hooks in the `fleche`
   entry-point group under the name `digest`; fleche loads them lazily the
   first time `digest()` hits a value it can't handle. Notably,
   [`fleche-ase`](https://pypi.org/project/fleche-ase/) ships hooks for
   ASE's `Atoms`, `VibrationsData`, and `Calculator` types — `pip install
   fleche-ase` and ASE objects digest correctly with no further setup, so
   don't hand-roll digests for ASE types.
3. A `__digest__` method on the class itself.

Full details: `docs/digests/entry_points.rst` (the entry-point mechanism,
fleche-ase, authoring your own plugin) and `docs/dev/custom_digests.rst`
(writing good digest functions).

Use `D(value)` (from `fleche`) to pass an existing digest/key as a lookup
shortcut instead of the real value — the cache expands it back to the
value before hashing. `D(value)` also accepts a stored value (returns its
digest) or a hex-digest string, so `cache().load_value(D(x))` retrieves a
value directly from either shape — see `docs/digests/digests_as_args.rst`
("Looking Up a Value Directly").

## Querying stored calls

```python
expensive.query().filter(...).table()   # pandas DataFrame of matching calls
expensive.query().latest()               # most recent call by timestamp
```

`QueryIterator` is chainable (`take`/`skip`/`filter`/`unique`/`sorted`);
terminal methods (`only`/`any`/`count`/`table`/`groupby`/`transfer`/`evict`)
consume it. Full API: `docs/usage/query.rst`.

## Security

Only pickle-family backends (`pickle`/`cloudpickle`/`dill`) support
signing. Set `secret_key` in the TOML section, or the `FLECHE_SECRET_KEY`
env var (colon-separated hex strings), to HMAC-sign stored entries; a
tampered or wrong-key entry surfaces as a cache miss (`KeyError`), not a
crash. Details: `docs/storage/security.rst`.
