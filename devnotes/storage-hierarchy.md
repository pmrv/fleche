# Storage Class Hierarchy

This document describes the class hierarchy of `fleche`'s storage subsystem
as of PR #245.

![Storage class hierarchy](storage-hierarchy.svg)

---

## Overview

The storage subsystem is split into six orthogonal layers:

| Layer | Purpose | Key types |
|---|---|---|
| **Key Management** | Shared key helpers | `KeyManagement` |
| **Abstract Backend** | Primitive `put`/`get` operations | `StorageBackend` |
| **Domain Interfaces** | Type-safe save/load contracts | `ValueStorage`, `CallStorage` |
| **Bridge Mixins** | Connect domain interfaces to a backend | `ValueMixin`, `CallMixin`, `DestructuringMixin` |
| **Backend Implementations** | Storage-medium logic (how data is stored) | `MemoryBackend`, `VoidBackend`, `PickleFileBackend`, … |
| **Typed Concrete Classes** | Mixin × Backend, ready to use | `ValueMemory`, `CallMemory`, `ValuePickleFile`, … |

---

## Layer 0 — `KeyManagement` (ABC)

```
KeyManagement(ABC)
├── list() : Iterable[Digest]   ← abstract
├── _evict(key)                 ← abstract
├── _contains(key) : bool       ← abstract
│
└── (concrete key-management helpers)
    ├── evict(key)          normalises str → Digest, then calls _evict()
    ├── contains(key) : bool
    ├── expand(key)         resolves a short prefix to the full digest
    └── shrink(key)         finds the shortest unambiguous prefix
```

`KeyManagement` is the root of all storage classes.  It provides the key-management
helpers shared across the entire hierarchy without coupling backends to the
`put`/`get` contract.  This allows `SqlBackend` to implement `CallStorage` directly
without inheriting from `StorageBackend`.

---

## Layer 1 — `StorageBackend` (ABC)

```
StorageBackend(KeyManagement)
├── put(value, key) : Digest    ← abstract
└── get(key) : Any              ← abstract
```

`StorageBackend` extends `KeyManagement` with the primitive `put`/`get` contract.
Any class that stores key-value pairs implements these two methods in addition to
the key-management abstractions inherited from `KeyManagement`.

---

## Layer 2 — Domain Interfaces (`ValueStorage`, `CallStorage`)

These ABCs express **what** is stored, independent of **how**:

```
ValueStorage(ABC)
├── save(value: Any, key?: Digest) : Digest
└── load(key: Digest | str) : Any

CallStorage(ABC)
├── save(call: Call) : Digest
└── load(key: Digest | str) : Call
```

Neither interface inherits from `StorageBackend`; both inherit from
`KeyManagement` directly.  This keeps the domain contracts free of backend
concerns, allows them to be type-checked in isolation, and lets
`SqlBackend` implement `CallStorage` without taking on the `put(value: Any)`
contract from `StorageBackend`.

---

## Layer 3 — Bridge Mixins (`ValueMixin`, `CallMixin`, `DestructuringMixin`)

The bridge mixins combine a domain interface with `StorageBackend` using
multiple inheritance, providing concrete implementations of `save`/`load`
in terms of `put`/`get`:

```python
class ValueMixin(ValueStorage, StorageBackend):
    def save(self, value, key=None):
        if key is None:
            key = digest(value)     # hash the value if no key given
        return self.put(value, key)

    def load(self, key):
        key = self.expand(key) if len(key) < DIGEST_LENGTH else Digest(key)
        return self.get(key)
```

```python
class CallMixin(CallStorage, StorageBackend):
    def save(self, call: Call):
        key = call.to_lookup_key()  # key derived from call identity
        if self.contains(str(key)):
            self.evict(str(key))    # evict stale entry before overwrite
        return self.put(call, key)

    def load(self, key):
        key = self.expand(key) if len(key) < DIGEST_LENGTH else Digest(key)
        return self.get(key)

    # Extra domain methods only meaningful for calls:
    def transform(self, func): ...
    def query(self, template: QueryCall): ...
```

`DestructuringMixin` hooks in at the *backend* level—it overrides `put`/`get`
on `StorageBackend` to transparently split nested collections (lists, dicts)
into individually-stored sub-values.  Because it inherits only from
`StorageBackend` it can be composed into either a value or call storage chain:

```python
class DestructuringValueMemory(ValueMixin, DestructuringMixin, MemoryBackend):
    pass
```

---

## Layer 4 — Backend Implementations

These classes implement the `StorageBackend` primitives (`put`/`get`/`_evict`/`list`)
for a specific storage medium.  They are **not** typed (value vs. call) — that
role belongs to the mixins above.

| Class | Storage medium | Notes |
|---|---|---|
| `MemoryBackend` | Python `dict` | Deep-copies on put/get to prevent aliasing; mutable, so not hashable |
| `VoidBackend` | Nothing (no-op) | Useful as a placeholder or in tests |
| `FileStorage` | Filesystem | Abstract; subclasses implement `_to_file`/`_from_file` |
| `PickleFileBackend` | Files (pickle/cloudpickle/dill) | HMAC-signed, optional gzip compression |
| `BagOfHoldingH5FileBackend` | HDF5 files | Via the `bagofholding` library |
| `SqlBackend` | SQLAlchemy (default: SQLite) | Stores `Call` fields in a relational schema; inherits `KeyManagement` directly (not `StorageBackend`) |

---

## Layer 5 — Typed Concrete Classes

Each typed concrete class is a one-liner that combines the appropriate mixin
with a backend implementation.  The naming convention is `{Value|Call}{Backend}`.

### Value storage (inherit from `ValueMixin`)

| Class | Backend |
|---|---|
| `ValueMemory` | `MemoryBackend` |
| `ValueVoid` | `VoidBackend` |
| `ValuePickleFile` | `PickleFileBackend` |
| `ValueBagOfHoldingH5File` | `BagOfHoldingH5FileBackend` |

### Call storage

| Class | Mixin/Base | Backend | Notes |
|---|---|---|---|
| `CallMemory` | `CallMixin` | `MemoryBackend` | |
| `CallVoid` | `CallMixin` | `VoidBackend` | |
| `CallPickleFile` | `CallMixin` | `PickleFileBackend` | |
| `CallBagOfHoldingH5File` | `CallMixin` | `BagOfHoldingH5FileBackend` | |
| `Sql` | `CallStorage` (direct) | `SqlBackend` | Inherits `CallStorage` directly — no `CallMixin`; `query()` uses SQL |

---

## Composition patterns

`Cache` (in `caches.py`) combines one value storage with one call storage:

```python
@dataclass
class Cache(BaseCache):
    values: ValueStorage    # e.g. ValueMemory() or ValuePickleFile(...)
    calls:  CallStorage     # e.g. CallMemory() or Sql()
```

To add destructuring to any backend, prepend `DestructuringMixin` in the MRO:

```python
class DestructuringValuePickleFile(ValueMixin, DestructuringMixin, PickleFileBackend):
    pass
```

---

## DOT source

The diagram above can be regenerated with:
`dot -Tsvg devnotes/storage-hierarchy.dot -o devnotes/storage-hierarchy.svg`

```dot
digraph StorageHierarchy {
    graph [
        rankdir=TB
        splines=ortho
        nodesep=0.6
        ranksep=0.8
        fontname="Helvetica,Arial,sans-serif"
        bgcolor="white"
    ]
    node [
        shape=record
        fontname="Helvetica,Arial,sans-serif"
        fontsize=11
        style="filled,rounded"
        margin="0.15,0.10"
    ]
    edge [
        fontname="Helvetica,Arial,sans-serif"
        fontsize=9
    ]

    /* ── Key management layer ───────────────────────────────── */
    subgraph cluster_keymanagement {
        label="Key Management"
        style=filled
        fillcolor="#F8F0FF"
        color="#9966CC"

        KeyManagement [
            label="{«ABC»\nKeyManagement|list()\l_evict(key)\l_contains(key)\l|evict(key)\lcontains(key)\lexpand(key)\lshrink(key)\l}"
            fillcolor="#DDB3FF"
            color="#6633AA"
        ]
    }

    /* ── ABC layer ─────────────────────────────────────────── */
    subgraph cluster_abc {
        label="Abstract Backend"
        style=filled
        fillcolor="#F0F4FF"
        color="#9999CC"

        StorageBackend [
            label="{«ABC»\nStorageBackend|put(value, key)\lget(key)\l}"
            fillcolor="#B3D9FF"
            color="#3366AA"
        ]
    }

    /* ── Domain interface layer ────────────────────────────── */
    subgraph cluster_domain {
        label="Domain Interfaces"
        style=filled
        fillcolor="#F5FFF0"
        color="#66AA66"

        ValueStorage [
            label="{«ABC»\nValueStorage|save(value, key?)\lload(key)\l}"
            fillcolor="#C8F5C0"
            color="#33AA33"
        ]

        CallStorage [
            label="{«ABC»\nCallStorage|save(call)\lload(key) → Call\l|transform(func)\l}"
            fillcolor="#C8F5C0"
            color="#33AA33"
        ]
    }

    /* ── Mixin / bridge layer ──────────────────────────────── */
    subgraph cluster_mixins {
        label="Bridge Mixins"
        style=filled
        fillcolor="#FFFBF0"
        color="#CCAA33"

        ValueMixin [
            label="{ValueMixin|Implements save/load\lusing put/get\l}"
            fillcolor="#FFEEAA"
            color="#AA8800"
        ]

        CallMixin [
            label="{CallMixin|Implements save/load\lusing put/get\lquery(template)\l}"
            fillcolor="#FFEEAA"
            color="#AA8800"
        ]

        DestructuringMixin [
            label="{DestructuringMixin|put(): splits collections\lget(): reassembles\lremaining_depth: int\l}"
            fillcolor="#FFE0AA"
            color="#CC7700"
        ]
    }

    /* ── Backend implementations ───────────────────────────── */
    subgraph cluster_backends {
        label="Backend Implementations"
        style=filled
        fillcolor="#FAFAFA"
        color="#AAAAAA"

        MemoryBackend [
            label="{MemoryBackend|storage: dict\l}"
            fillcolor="white"
            color="#888888"
        ]

        VoidBackend [
            label="{VoidBackend|no-op backend\l}"
            fillcolor="white"
            color="#888888"
        ]

        FileStorage [
            label="{«abstract»\nFileStorage|root: Path\l_to_file(value, path)\l_from_file(path)\l}"
            fillcolor="#F0F0F0"
            color="#888888"
            style="filled,rounded,dashed"
        ]

        PickleFileBackend [
            label="{PickleFileBackend|serializer (pickle/cloudpickle/dill)\lsecret_key, compress\l}"
            fillcolor="white"
            color="#888888"
        ]

        BagOfHoldingH5FileBackend [
            label="{BagOfHoldingH5FileBackend|HDF5 via bagofholding\l}"
            fillcolor="white"
            color="#888888"
        ]

        SqlBackend [
            label="{SqlBackend|url: str\lSQLAlchemy-backed\l}"
            fillcolor="white"
            color="#888888"
        ]
    }

    /* ── Typed value classes ───────────────────────────────── */
    subgraph cluster_value_typed {
        label="Typed Value Classes"
        style=filled
        fillcolor="#F0FFF4"
        color="#66AA88"

        ValueMemory             [label="{ValueMemory\l}",              fillcolor="#C8F5D8", color="#33AA66"]
        ValueVoid               [label="{ValueVoid\l}",                fillcolor="#C8F5D8", color="#33AA66"]
        ValuePickleFile         [label="{ValuePickleFile\l}",          fillcolor="#C8F5D8", color="#33AA66"]
        ValueBagOfHoldingH5File [label="{ValueBagOfHoldingH5File\l}", fillcolor="#C8F5D8", color="#33AA66"]
    }

    /* ── Typed call classes ────────────────────────────────── */
    subgraph cluster_call_typed {
        label="Typed Call Classes"
        style=filled
        fillcolor="#F0F4FF"
        color="#6688AA"

        CallMemory              [label="{CallMemory\l}",               fillcolor="#C8D8F5", color="#3366AA"]
        CallVoid                [label="{CallVoid\l}",                 fillcolor="#C8D8F5", color="#3366AA"]
        CallPickleFile          [label="{CallPickleFile\l}",           fillcolor="#C8D8F5", color="#3366AA"]
        CallBagOfHoldingH5File  [label="{CallBagOfHoldingH5File\l}",  fillcolor="#C8D8F5", color="#3366AA"]
        Sql                     [label="{Sql\l}",                      fillcolor="#C8D8F5", color="#3366AA"]
    }

    /* ── Inheritance: key management root ─────────────────── */
    KeyManagement -> StorageBackend [arrowhead=onormal, style=solid]
    KeyManagement -> ValueStorage   [arrowhead=onormal, style=solid]
    KeyManagement -> CallStorage    [arrowhead=onormal, style=solid]
    KeyManagement -> SqlBackend     [arrowhead=onormal, style=solid]

    /* ── Inheritance: mixins ───────────────────────────────── */
    ValueStorage -> ValueMixin      [arrowhead=onormal, style=solid]
    StorageBackend -> ValueMixin    [arrowhead=onormal, style=solid]
    CallStorage -> CallMixin        [arrowhead=onormal, style=solid]
    StorageBackend -> CallMixin     [arrowhead=onormal, style=solid]
    StorageBackend -> DestructuringMixin [arrowhead=onormal, style=solid]

    /* ── Inheritance: backends ─────────────────────────────── */
    StorageBackend -> MemoryBackend             [arrowhead=onormal, style=solid]
    StorageBackend -> VoidBackend               [arrowhead=onormal, style=solid]
    StorageBackend -> FileStorage               [arrowhead=onormal, style=solid]
    FileStorage -> PickleFileBackend            [arrowhead=onormal, style=solid]
    FileStorage -> BagOfHoldingH5FileBackend    [arrowhead=onormal, style=solid]

    /* ── Inheritance: typed value classes ──────────────────── */
    ValueMixin -> ValueMemory               [arrowhead=onormal, style=solid]
    MemoryBackend -> ValueMemory            [arrowhead=onormal, style=solid]
    ValueMixin -> ValueVoid                 [arrowhead=onormal, style=solid]
    VoidBackend -> ValueVoid                [arrowhead=onormal, style=solid]
    ValueMixin -> ValuePickleFile           [arrowhead=onormal, style=solid]
    PickleFileBackend -> ValuePickleFile    [arrowhead=onormal, style=solid]
    ValueMixin -> ValueBagOfHoldingH5File  [arrowhead=onormal, style=solid]
    BagOfHoldingH5FileBackend -> ValueBagOfHoldingH5File [arrowhead=onormal, style=solid]

    /* ── Inheritance: typed call classes ───────────────────── */
    CallMixin -> CallMemory                 [arrowhead=onormal, style=solid]
    MemoryBackend -> CallMemory             [arrowhead=onormal, style=solid]
    CallMixin -> CallVoid                   [arrowhead=onormal, style=solid]
    VoidBackend -> CallVoid                 [arrowhead=onormal, style=solid]
    CallMixin -> CallPickleFile             [arrowhead=onormal, style=solid]
    PickleFileBackend -> CallPickleFile     [arrowhead=onormal, style=solid]
    CallMixin -> CallBagOfHoldingH5File    [arrowhead=onormal, style=solid]
    BagOfHoldingH5FileBackend -> CallBagOfHoldingH5File [arrowhead=onormal, style=solid]
    CallStorage -> Sql                      [arrowhead=onormal, style=solid]
    SqlBackend -> Sql                       [arrowhead=onormal, style=solid]
}
```
