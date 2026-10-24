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

## Module map

**Pipeline:** `wrapper.py` (decorator) → `call.py` (key building) → `digest.py` (hashing) → `caches.py` (cache objects) → `storage/` (backends).

**Public API (`fleche.__init__`):** `__version__`, `fleche`, `cache`, `meta`, `tags`, `project`, `BoundWrapper`, `Ignored`, `Required`, `D`, `wrap_executor`.
`SshCache` is not exported — reach it via `type="ssh"` config or `fleche.remote`.
`D(value)` passes non-empty hex strings (≤64 chars) through verbatim as lookup keys and digests anything else;
`Digest` arguments to a wrapped function are expanded back to their value before hashing.

**Backends (config `type` strings):** `"memory"`, `"void"`, `"pickle"` / `"cloudpickle"` / `"dill"`, `"bagofholding_hdf"`, `"sql"` (**calls only**), `"ssh"` (whole-cache forwarding).
Values and calls are stored separately so call records are queryable without deserializing heavy values.

### Core modules

- `state.py` — the active cache is a `ContextVar` with **no default**;
  `get_cache()`/`get_metadata()` fall back to config loaded lazily on first access and memoised in `_DEFAULTS` (clear it to force a re-read, as the config tests do).
  `cache(c)`/`meta(...)` set immediately and return a sticky context: `with` restores, discarding keeps the change.
  `cache(x, stack=True)` puts `x` in front of the current cache as a `CacheStack`.
  `BoundWrapper` pins cache + metadata at `.bind()` time and re-installs them around each call (metadata reset before cache);
  it is how calls cross pickle and executors.
- `wrapper.py` — the decorator and its helpers (`.call/.digest/.load/.contains/.query/.rerun/.bind`, mirrored on `.fleche.*`), registered via `_PRE_WRAPPER_SPECS`/`_POST_WRAPPER_SPECS`.
  Two-phase save: `cache.prepare(call)` seals the key *before* the body runs, so an argument-mutating body cannot leak into it.
  Any prepare failure runs the call uncached;
  a body exception, `None` result, failing `Future` or `RefreshingCache` evict calls `abandon()`;
  success calls `commit()` (for futures, from `add_done_callback`).
  `wrapper.__digest__ = partial(digest, func)` keeps decoration digest-transparent;
  without it every wrapper would digest as fleche's own closure.
  `_in_flight_lock` is a `_PicklableLock` so the closure survives cloudpickle-by-value.
- `call.py` — `Call` → `DigestedCall` (storage form, `Digest` keys;
  `result is None` means admitted by `prepare` but not committed) → `LazyCall` (deferred deserialisation), and back.
  `PreparedCall` is the two-phase middle state: a context manager that auto-abandons, never hashed or sent over the wire.
  `QueryCall` matches wildcards and ignores `code_digest` unless set.
  `Call`, `DigestedCall` and `LazyCall` must digest identically when their fields agree.
  `FunctionProfile.of(func)` gathers all static per-function metadata;
  for an unimportable module, `version` falls back to the function's own `__version__`, not `None`.
- `digest.py` — `digest()` is the single public entry point;
  on `Indigestible` it loads entry points and retries once.
  Precedence: hooks and entry points first (for third-party types;
  skipped when both hook lists are empty), then a class-level `__digest__` (still before the built-in `match` arms so dict/list subclasses can override;
  negatives cached in `_TYPES_WITHOUT_DIGEST`), then the `_digest_bytes` match.
  Order-sensitive arms: `np.timedelta64` goes to `_numpy.digest_timedelta64` before `Number` (numpy registers it as `Integral`);
  pandas comes before `Iterable` (a DataFrame iterates its column names) and before the `datetime.timedelta` arm (`pd.Timedelta` subclasses it).
  A `datetime.timedelta` digests its exact length in microseconds, not the old `total_seconds()` float, which merged unequal values past about 285 years.
  Built-in `type` objects digest by name, user classes are `Indigestible` as values;
  dataclass and `attrs` instances share one flat field-dict layout.
  Functions digest code plus captured cells and defaults, so closures from one factory differ (a function with neither digests as its code object);
  cycles fold a relative-depth marker, the `__class__` cell is named via `digest_class`, and `__digest__` is honoured per instance.
  `CO_NESTED` is part of the code, so un-nesting a helper changes its key (`test_nesting_changes_a_function_digest`).
- Digest arm modules (`_numbers`, `_numpy`, `_pandas`) are kept out of `digest.py` and take `_digest_bytes` as an argument to avoid import cycles.
  `_hashing.py` is the only home of the hash primitive they share (patch `_hashing.hashlib` to swap it everywhere);
  the hex encoding lives only there and in `digest.py`.
  `_numbers.py` walks `NUMBER_TREE`: non-NaN numbers digest equal iff they hold the same exact value (numpy's `==` is not the reference), converters must refuse inexact conversions themselves, NaNs digest by their float/complex bits, and `int` subclasses keep their own type name while `float` subclasses downcast.
  The tree is also drawn in a code comment and in `docs/digests/digest_equivalence.rst` — update both by hand.
  Equal values of different numeric types share one stored value, and the last save wins the return type — intended.
  `_numpy.py` digests dtype + shape + bytes, except structured dtypes (per field;
  padding is uninitialised) and object dtypes (per element).
  Timedeltas stay apart per library (`datetime.timedelta`, `pd.Timedelta` and `np.timedelta64` of one length are three digests, by maintainer decision), each by its exact length.
  A fixed-unit `np.timedelta64` digests its length in attoseconds (numpy's finest unit, as a Python int), so the unit never matters and numpy's int64 cross-unit `==`, which can wrap, is not the reference;
  `Y`/`M` digest as months, the generic unit as its bare count (numpy's `5 == 5 s == 5 ms` is not transitive), and NaT as one constant.
  `_pandas.py` folds name/dtype/index in by hand (`hash_pandas_object` ignores them) and digests non-string object columns element-wise with fleche's own hash (pandas would `str()` them).
  A `pd.Timedelta` digests its exact length in nanoseconds through `to_timedelta64()`, not `.value`, which overflows beyond int64 ns;
  `pd.NaT` is a `datetime.datetime` subclass and keeps its datetime-arm digest.
  `_attrs.py` is import-safe without `attrs`.
- `caches.py` — every `BaseCache` has `prepare(call) → PreparedCall` and `save(PreparedCall | Call)`.
  `Cache.prepare` stashes argument values at once, and `save` only resolves the result;
  `CacheWrapper.prepare` delegates and rebinds `PreparedCall.cache = self` so wrapper policy governs the commit;
  read-only caches admit digest-only and reject at `save`.
  Wrappers are `CacheWrapper` (forwards everything) plus behaviour mixins;
  `ReadOnlyMixin` is field-free and base-free, goes **first** in the bases, and is the marker `remote._is_read_only` checks.
  `FilteringMixin` filters `load`/`_query` by a predicate;
  `FilteredCache(ReadOnlyMixin, FilteringMixin)` is its read-only combination.
  `_MultiCache` owns fan-out via `_first_hit`/`_collect`/`_foreach` — write new multi-cache methods over these.
  `CacheStack` writes to `stack[0]` (the "lowest"), back-fills read hits into it, and cannot nest;
  `CachePool` is read-only, first-hit-wins, and never back-fills.
  Per-key locking: `_transfer_one` holds `_operation_context(key)` across `contains`→`save`;
  `CacheWrapper` forwards `_operation_context` and `CacheStack` really locks only `stack[0]` (the rest enter with `Intent.READ`), so wrapped targets lock their real cache;
  `redigest` holds old- and new-key locks;
  `CacheStack.load` serialises back-fill.
  Never mix call and value keys in one `Cache.shrink`.
  `redigest` has no rollback, by design;
  `gc` is mark-and-sweep, following sub-references when the value storage satisfies `HasChildDigests`.
  `SizeLimitedMixin` scans every call at init (#920) and evicts at random — override `_pick_eviction_target`.
- `query.py` — `QueryIterator.calls` is a zero-arg factory, so an iterator is re-iterable and reflects current cache state.
  `.table()` shrinks keys to unambiguous prefixes by default (`shrink_keys=False` on big caches) and prefixes clashing argument names with `a_`.
  `latest`/`oldest` need `Runtime` metadata: `ValueError` if no match carries it, `IndexError` if nothing matches.
- `metadata.py` — `@configurable` registers a `MetaData` class in `CONFIGURABLE` under its PascalCase name (what TOML uses) and sets `name` to the lowercase name;
  `Tags` needs constructor args, so it is not configurable.
  Static schemas live in `_keys: ClassVar`, which a test checks against `pre`/`post` output.
  `Runtime.cputime`/`systime` include child processes and are omitted (not `None`) where `resource` is missing.
- `config.py` — loading and round-tripping, see [Config](#config).
  Named caches are interned in `_live_caches` (the default also under `None`), so a name always returns one instance and SSH/file backends aren't reopened.
- `security.py` — `SignedBytes` HMAC is hex-encoded so it never contains the pickle STOP byte, which is how `loads` finds the signature.
  Only pickle-family backends sign;
  the first key signs and all keys verify;
  a `SignatureError` surfaces as `KeyError` (a miss).
- `executor.py` — `wrap_executor` patches `.submit`: cached calls return a completed `Future`, and every other callable is `BoundWrapper`-bound so nested fleche calls see the active cache.
- `__main__.py` — `python -m fleche remote --serve`, routed here rather than `python -m fleche.remote` so `runpy` doesn't import `remote.py` twice.
- `remote.py` — `SshCache` forwards every cache op over one persistent SSH subprocess with length-prefixed **cloudpickle** frames.
  The `info` handshake warns on version skew and caches `read_only`;
  `info()` output is redacted (secret keys, URL passwords) because it is ordinary user-visible data.
  Server `_REMOTE_METHODS` and client `_CLIENT_METHODS` change together (#737).
  `prepare` ships the `Call` and gets back the sealed `DigestedCall`;
  `save(prepared)` is two RPCs, and a failure between them leaves a `gc`-able orphan.
  `Path` arguments ship as strings, not content (#829).

### Storage (`storage/`)

- `base.py` — `OperationContext` is the root of both storage and cache hierarchies;
  chain `_operation_context` via `super()._operation_context(key, intent=intent)`.
  `Intent.READ` is a **no-op** placeholder for a future shared lock — never use it to guard a read-modify-write.
  `KeyManagement.expand` rejects prefixes under 4 chars;
  subclasses override only `_prefix_candidates`.
  `ValueMixin`/`CallMixin` bridge `save`/`load`/`query` onto `put`/`get`.
  `@register_storage(name, kind)` on a backend class fills the config dispatch table.
  There is deliberately no inherited `to_config`: each concrete class writes its own, and `storage_to_config` checks the exact class so a subclass can't round-trip as its parent.
- `file.py` — `FileStorage` is **lock-free**: `put` writes a dot-prefixed temp sibling and renames it into place, so `_to_file` must write a complete file at whatever path it gets.
  `list()` skips `*.lock` and dot-files;
  legacy `*.lock` litter is deliberately not swept.
- `pickle_file.py` — serializers come from a lazily-importing `_SERIALIZERS` registry;
  gzip is detected by magic on read.
- `bagofholding_file.py` — the only backend that still locks (`filelock`, `lock_timeout`), and only in **multi-bag** mode (`prefix_length > 0`, default `2`), where one `.h5` is shared by keys and mutated in place.
  `prefix_length=0` is one file per key and lock-free;
  `None` infers from existing files, and a mismatch with files in `root` raises at construction.
  `refix(n)` / `consolidate(root, n)` migrate layouts.
  Check #893 before touching `lock_timeout`.
- `memory.py` — `put`/`get` deep-copy.
- `sql.py` — `Sql` stores calls only and is not a `StorageBackend`: it saves in one transaction and evicts with one `DELETE`, child rows going by `ON DELETE CASCADE` (SQLite needs `foreign_keys=ON` per connection).
  `query` always pushes name/module/version/code/argument filters to SQL, metadata filters only when every value is a simple scalar, and re-checks metadata in Python regardless.
  `journal_mode` is set once per database: `WAL`, or `DELETE` on a network filesystem.
  `:memory:` is detected via `engine.url.database`, since the rendered URL percent-encodes it.
  MySQL needs `VARCHAR(255)` on indexed columns.
- `destructuring.py` — `DestructuringMixin` stores containers, dataclasses and attrs instances as separately stored parts (`remaining_depth`), composed **above** `ValueMixin`.
  `Digested*` markers keep digest equivalence via `__digest__` and rebuild fields via `object.__new__` + `__setattr__`, so `init=False`/`InitVar`/frozen/slots round-trip.
  NamedTuples are not destructured.
  `register_destructurer` appends to `_DESTRUCTURERS`, first match wins.
- `thread_safe.py` — `SerializingMixin` and `PerKeyLockMixin` (striped locks keyed by the instance, so instances must be **hashable**) subclass `OperationContext` directly, so they attach at either layer.
  `_PicklableLock`/`_PicklableRLock` pickle without state — in-process only.

**Composition:** concrete classes are `@dataclass(frozen=True)` composed by MRO, with locking already baked in — do not wrap them again: `Cache(PerKeyLockMixin, BaseCache)`,
`CacheStack(PerKeyLockMixin, _MultiCache)`,
`CachePool(ReadOnlyMixin, _MultiCache)`,
`ValueMemory(PerKeyLockMixin, DestructuringMixin, ValueMixin, MemoryBackend)`,
`CallMemory(PerKeyLockMixin, CallMixin, MemoryBackend)` (file and HDF5 pairs follow the same pattern),
`Sql(PerKeyLockMixin, CallStorage)`;
`ValueVoid`/`CallVoid` have no lock.
Dataclass fields from every base merge into one `__init__`, so don't pass `init=False` on user-facing fields;
internal state uses `field(init=False, repr=False, compare=False)` and is rebuilt in `__post_init__`.
`MemoryBackend` subclasses need `__hash__ = object.__hash__` (frozen dataclasses regenerate `__hash__`, and the `dict` field is unhashable);
`__init_subclass__` enforces it.

## Architecture notes

### Core data flow

1. Decoration builds a `FunctionProfile`;
   `code_digest` hashes code plus captures and defaults, falling back to code-only (with a warning) when those can't be digested.
2. On call: `Digest` args expanded → `Call.from_call()` binds and applies defaults (so defaults reach the key regardless of `hash_code`) → ignored args stripped → `to_lookup_key()` → `digest()`.
3. Hit → stored result;
   miss → `pre` hooks, `prepare`, execute, `post` hooks, `commit`.
4. Runs uncached on a `None` return (warning), an `Indigestible` argument, or a missing `Required` kwarg.

### Cache key control

Decorator kwargs: `version`, `meta`, `hash_version`, `hash_module`, `hash_code`, `require`/`ignore`, `isolate` (tempdir via `os.chdir` — **not thread-safe**);
per-argument `Ignored[T]` / `Required[T]`.
`hash_code=False` stays the default because flipping it invalidates every cache, so closures from one factory share an entry unless `hash_code=True`.

### Config

`cache_from_config(d)` dispatches in order: list → `CacheStack`;
`pool` → `CachePool`;
`template` → expand via `_CACHE_TEMPLATES` and recurse;
`type="ssh"` → `SshCache`;
`max_size` → `SizeLimitedCache`;
else `Cache`;
`read_only: true` then wraps it in `ReadOnlyCache`.
`BaseCache.from_config` imports `config` lazily (module level would be circular) and may return another class than `cls`.
`_load_config` rebases relative `root`/`url` onto each file's directory before merging;
programmatic values still resolve against the CWD.
The type reference is `config.py`'s module docstring;
discovery and merge rules are in [USAGE.md](USAGE.md#config-files--where-fleche-looks-and-whats-in-them).

## Test layout

- `unit/<module>/` mirrors the source (`caches/`, `call/`, `config/`, `digest/`, `fleche/`, `metadata/`, `storage/`), filenames named after the feature;
  `integration/` is end-to-end (including every notebook via `test_notebooks.py`);
  `regression/test_issue_<N>.py` is one file per issue;
  `smoke/` is one round-trip per optional dep (`pytest -m smoke`).
- `tests/conftest.py` makes `import test` fail on every interpreter, so no test may rely on CPython's optional `test` package.
- Gate optional deps with `pytest.importorskip` or a `skipif` on an import flag — never a bare `try/except ImportError`.
- `tests/fixtures.py`: `call_storage` / `value_storage` / `storage_backend` are parametrised over every backend — add a new backend there (three spots: `_build_value_storage`, `_build_call_storage` and `storage_backend` itself, #791).
  `paired_storages` sweeps `(value_storage, call_storage)` pairs diagonally rather than crosswise.
  `FLECHE_TEST_POSTGRES_URL` / `FLECHE_TEST_MYSQL_URL` add real-server `Sql` cases.
  `clean_cache` is not activated — use `with cache(clean_cache):`.
  Concurrency tests share `run_workers()`.
- Deleting tests: redundancy is collective, so "covers nothing uniquely" is no criterion;
  remove only tests strictly weaker than a same-file sibling, keeping per-file coverage identical.

## Other directories

- `docs/` — Sphinx;
  `docs/figures/` SVGs are checked in (the RTD builder has no `dot`), and `gen_diagrams.py` also refreshes the PNGs embedded in `notebooks/Destructuring.ipynb`.
  `docs/notebooks/` is symlinks, so a new notebook needs one.
- `.github/workflows/` — `test-minimum-deps.yml` uses `uv pip install --resolution lowest-direct` (not `uv sync`, whose lock floats deps up) in a venv pinned to the `requires-python` floor — keep the pin in sync.
  `perf-triage.yml` adds the `benchmark` label that triggers `benchmarks.yml`;
  `rendernb.yml` re-executes notebooks on the `rendernb` label.
  `ci-failure-summary.yml` triages every failed or timed-out run of the workflows in its `workflows:` list, bot-triggered runs included;
  the workflow downloads the failed-job logs, a Claude confined to Read/Grep/Glob inside that directory (no shell, no network, no GitHub token) writes the summary, and the workflow posts it — a PR comment, or an issue when no PR is found;
  it is shared with landau and assyst, and only its `workflows:` list may differ between the repos — keep the rest portable.
  The in-PR Claude app can't push under `.github/workflows/`;
  those edits need a maintainer.

## Design themes / open scope (issue tracker)

Map of open design work.
Issue numbers are the entry points — fetch them before re-litigating.
This section tracks **current state only**: when a PR merges, move whatever an agent needs to know into the reference sections above and delete its entry here.
Git history is the changelog — no PR numbers, dates or release versions here.

**Open design directions**

- Concurrency (#444): `gc` #450, `expand` lock scope #453, gc vs in-flight `PreparedCall` #826;
  `BackgroundSaveMixin` #447 for off-hot-path I/O.
- Performance (#625, read its newest comment;
  #440): raw-bytes digests behind a `hash_version` bump, `blake2b` switch (#615), double cache+storage locking, HDF5 open per access, `Sql` fsync per key.
- Cold value tier for HPC (#552).
- Config redesign (#568), explicit config location (#1019), Linux-only XDG assumptions (#868, #885).
- Path handling (#516, #517, #522, #33): files stored by content, restored as `TempPath`s;
  in progress on the `temppath` branch.
- Query expressiveness (#87, #82);
  eviction policies (#161, #6);
  digest dispatch registry (#333, #834);
  enum digests (#1022, `Flag` members currently raise `RecursionError`).
- Re-keying after a module rename (#942 has a tested recipe).
- Central SQL call index on HPC (#1047 is the field report and entry point): no compute fallback when the server is down, hosted-server tooling and its config write-back,
  `autostart` on shared cluster nodes.

**Known bugs**: #826 gc vs `PreparedCall`;
#840 `BoundWrapper` needs `fork`;
#893/#903 multi-bag `filelock.Timeout` under contention;
#895 cache hits return a plain `Future` (accepted);
#916 `.query()` with `hash_version=False`/`hash_module=False` (fix on branch `fix/query-hash-flags-916`);
#918 destructuring ignores digest hooks;
#883 custom destructurers hide children from `gc`;
#1047 concurrent workers computing the same call on the `sql` backend can raise `IntegrityError` out of the decorated function (a duplicate insert should count as a hit; also #790, #218).

**Feature requests**: #829, #854, #855.

**Open refactor issues**, by area (check before refactoring nearby): `wrapper.py`/`call.py`/`executor.py` #639, #788, #901, #960, #961;
`caches.py` #688, #710, #711, #761, #762, #789, #809, #920, #921;
`config.py` #708, #884, #922;
`remote.py` #737, #832, #835, #944;
`digest.py` #834, #923;
`storage/` #739, #760, #790, #833, #866, #974, #975;
`metadata.py` #902;
`query.py` #962;
tests/tooling #791, #867, #869, #886, #899, #982, #983;
CI/packaging #900, #945, #946, #947, #976, #985.

**Standing decisions**

- Cache-key-invalidating changes ship without a `hash_version` bump;
  say so in the commit body and point at `Cache.redigest()`.
- README's "Thread-Safe" bullet overclaims;
  ask the maintainer before reopening #950.

**Out of scope / deferred**

- MPI-rank-parallel caching in core (#870): rejected, belongs in an addon;
  lookup keys carry no rank, so ranks can diverge on hit/miss and skip collectives.
- Parked for 2.0: #170, #93, #99, #82.
  `backburner`: #333, #404.
- Terminology "cache" → "stash" (#350), `.fleche.*` naming (#222), "cache-oriented programming" (#70).

## Commit messages

Always write commit messages in the [Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/) format (`<type>[optional scope]: <description>`, e.g. `feat:`, `fix:`, `docs:`, `test:`, `chore:`, `refactor:`).
This repo's releases are driven by **release-please**, which derives version bumps and changelog entries from the conventional-commit history on `main` — non-conforming messages are ignored by the release tooling.
Use `!` after the type/scope (or a `BREAKING CHANGE:` footer) for breaking changes — **but never while the project is below 1.0**.
Release-please turns a breaking marker on an `0.x` version into `1.0.0`, so a change that merely invalidates cache keys would cut the first stable release as a side effect.
Pre-1.0, such a change is a `fix:` (or `feat:`) whose body explains the invalidation and points at `Cache.redigest()`;
the version bump is not the place to carry that warning.

## Commit attribution

When running inside a GitHub Action, git may be authenticated as someone other than you (`.github/workflows/claude.yaml` authenticates through `claude-code-action`'s OAuth token;
no workflow carries a user PAT).
Without intervention, any commits you create would be attributed to that identity.
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
