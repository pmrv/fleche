# AGENTS.md

Cross-tool entry point for AI coding agents (Codex, Cursor, Aider, Claude, ...).

**Fleche** is a persistent function cache for Python (`@fleche()`) — like
`lru_cache` but it survives restarts, with blake2b content-based keys and
pluggable storage backends (memory, pickle-family, HDF5, SQL, SSH).

This file is deliberately short. Pick the guide that matches what you're doing:

| Task | Guide |
|---|---|
| Writing code that *calls* fleche — decorating functions, configuring a cache via `fleche.toml`, choosing a storage backend, querying stored calls | **[agents/USAGE.md](agents/USAGE.md)** |
| Changing fleche's *own* source — commands, tests, module map, architecture internals, the design/issue-tracker history, commit conventions | **[agents/DEVELOPING.md](agents/DEVELOPING.md)** |

Full human-facing docs (Sphinx) live in `docs/`; runnable examples live in
`notebooks/`.

## In a hurry

```bash
pip install -e ".[tests]"     # install with test deps
pytest tests/                 # run tests
ty check src/                 # type check
```

Python `>=3.11,<3.15`. Conventional Commits are required on every commit
message (`feat:`/`fix:`/`docs:`/`test:`/`chore:`/`refactor:`) — see
[agents/DEVELOPING.md](agents/DEVELOPING.md#commit-messages) for why and how.
