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
`put`/`get` contract.  This allows `Sql` to implement `CallStorage` directly
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
`Sql` implement `CallStorage` without taking on the `put(value: Any)`
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
| `Sql` | `CallStorage`, `KeyManagement` (direct) | — | Full SQL implementation; no `CallMixin`; `query()` uses SQL directly |

`Sql` is the exception to the Mixin × Backend pattern: it inherits `CallStorage`
and `KeyManagement` directly and implements all SQL operations itself using
SQLAlchemy, rather than delegating to a separate backend class.

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

## Regenerating the diagram

```
dot -Tsvg devnotes/storage-hierarchy.dot -o devnotes/storage-hierarchy.svg
```
