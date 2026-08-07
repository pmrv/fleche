import cmath
import datetime
import hashlib
import logging
import dataclasses
import numbers
from numbers import Number
import struct
import subprocess
from pathlib import Path
import types
import importlib.metadata
from collections.abc import Iterable, Mapping
from typing import Any, TypeVar, Callable, Type, Generic
import numpy as np
import pandas as pd

from . import _attrs

logger = logging.getLogger("fleche.digest")


class Indigestible(Exception):
    """Exception raised when an object cannot be digested."""

    pass


class Digest(str):
    def expand(self, cache=None) -> "Digest":
        """Expand a short digest prefix to its full-length digest using the cache.

        Args:
            cache: A cache instance to use. If None, uses the current context's cache.

        Returns:
            The full-length :class:`~fleche.digest.Digest`.
        """
        if cache is None:
            from .state import cache as get_cache
            cache = get_cache()
        return cache.expand(self)

    def shrink(self, cache=None) -> "Digest":
        """Shrink a digest to its shortest unambiguous prefix using the cache.

        Args:
            cache: A cache instance to use. If None, uses the current context's cache.

        Returns:
            The shortest unambiguous :class:`~fleche.digest.Digest` prefix.
        """
        if cache is None:
            from .state import cache as get_cache
            cache = get_cache()
        return cache.shrink(self)


DIGEST_LENGTH = 64


T = TypeVar("T")


@dataclasses.dataclass
class Hook(Generic[T]):
    type: T
    digest: Callable[[T], str | Digest]


_HOOKS = []
_EP_HOOKS = []

# Types confirmed *not* to define ``__digest__``.  ``__digest__`` is the opt-in
# protocol that lets user types (including subclasses of dict/list/...) take
# over their own digest, so the check has to run before the built-in ``match``
# cases — which means it executes on every recursive ``_digest_bytes`` call for
# plain ints, strs, dicts, lists, etc., where the answer is always False.  After
# the first sighting of each built-in type, a set-membership check skips the
# ``hasattr`` MRO walk entirely.  No semantic change for class-defined
# ``__digest__`` (instance-level dunders are not supported anyway).
_TYPES_WITHOUT_DIGEST: set[type] = set()


def get_hooks():
    return list(reversed(_HOOKS)) + _EP_HOOKS


def add_hook(hook: Hook | tuple[Type[T], Callable[[T], str]]):
    if isinstance(hook, tuple):
        hook = Hook(*hook)  # ty: ignore
        _HOOKS.append(hook)
    elif isinstance(hook, Hook):
        _HOOKS.append(hook)
    else:
        raise ValueError("Must be a Hook instance or (type, digest function) tuple!")


def load_entry_points():
    _EP_HOOKS.clear()
    eps = importlib.metadata.entry_points(group="fleche", name="digest")

    seen_types = {h.type: "add_hook" for h in _HOOKS}

    for ep in eps:
        try:
            hooks = ep.load()
            if not isinstance(hooks, list):
                hooks = [hooks]

            for hook in hooks:
                if isinstance(hook, tuple):
                    hook = Hook(*hook)

                if hook.type in seen_types:
                    source = seen_types[hook.type]
                    if source == "add_hook":
                        logger.info(
                            "add_hook for %s overrides entry point %s",
                            hook.type,
                            ep.value,
                        )
                    else:
                        for h in _EP_HOOKS:
                            if (h.type is not hook.type) and (
                                h.digest is not hook.digest
                            ):
                                logger.info(
                                    "Digest from %s overrides later entry point %s!",
                                    source,
                                    ep.value,
                                )
                    continue

                _EP_HOOKS.append(hook)
                seen_types[hook.type] = ep.value
        except Exception as e:
            logger.error("Failed to load entry point %s: %s", ep.name, e, exc_info=True)


def _digest_mapping(m, contents: Mapping) -> bytes:
    sorted_items = sorted(
        ((_digest_bytes(k), k, v) for k, v in contents.items()), key=lambda item: item[0]
    )
    for k_bytes, k, v in sorted_items:
        m.update(k_bytes)
        m.update(_digest_bytes(v))
    return m.hexdigest().encode()


def digest(value: Any) -> Digest:
    try:
        return Digest(_digest_bytes(value).decode())
    except Indigestible:
        load_entry_points()
    return Digest(_digest_bytes(value).decode())


def _path_content_digest(path) -> Digest:
    """Content-only digest of a path: a file as its bytes, a directory as its
    ``{name: child}`` tree (the directory's own name excluded).

    This mirrors exactly what :class:`~fleche.storage.paths.PathValueMixin`
    stores for a file's content blob and for a :class:`DirectoryBlob`, so a
    directory tree and a standalone file agree on their children's digests.  A
    *standalone* file additionally carries its basename (see the ``Path`` arm of
    :func:`_digest_bytes`); inside a directory the name lives in the parent's
    ``contents`` key, so only the content matters here.
    """
    if path.is_file():
        return digest(path.read_bytes())
    if path.is_dir():
        contents = {
            child.name: _path_content_digest(child)
            for child in path.iterdir()
            if child.is_file() or child.is_dir()
        }
        return digest(("DirectoryBlob", contents))
    raise Indigestible("Can only digest files and folders!")


def _digest_bytes(value: Any) -> bytes:
    """
    Returns bytes representing the SHA-256 digest of *value*.

    All recursive call sites pass the result directly to ``m.update()``.

    **Wire-format note**: currently returns ``m.hexdigest().encode()`` (64 UTF-8
    hex bytes) so the bytes fed into parent hashes are identical to the previous
    ``digest(v).encode()`` calls — no backwards-incompatible change.  To gain
    the raw-bytes speedup (Issue #440), change **only** the final ``return``
    here to ``m.digest()`` (32 bytes), update ``digest()`` to call ``.hex()``
    instead of ``.decode()``, and change the ``encode()`` calls on the
    early-return paths (Digest pass-through, hooks, ``__digest__``) to
    ``bytes.fromhex(...)``.  That must be coordinated with a ``hash_version``
    bump and a ``Cache.redigest`` migration.
    """
    m = hashlib.sha256()

    # Fast-path: in the common case both hook lists are empty, so skip the
    # ``get_hooks()`` call which would otherwise allocate a fresh combined list
    # on every recursive ``_digest_bytes`` invocation (hot for large iterables).
    if _HOOKS or _EP_HOOKS:
        for h in get_hooks():
            if isinstance(value, h.type):
                return h.digest(value).encode()

    # ``__digest__`` opt-in protocol must win over the built-in ``match`` cases
    # so dict/list subclasses can override their own digest.  Avoid the
    # per-call ``hasattr`` MRO walk for the overwhelming common case (plain
    # built-ins) by caching the negative answer in ``_TYPES_WITHOUT_DIGEST``.
    t = type(value)
    if t not in _TYPES_WITHOUT_DIGEST:
        if hasattr(t, "__digest__"):
            # For raw-bytes speedup (Issue #440): bytes.fromhex(value.__digest__())
            return value.__digest__().encode()
        _TYPES_WITHOUT_DIGEST.add(t)

    m.update(t.__name__.encode())
    match value:
        case int():
            # Most-frequent arm; bool ⊂ int so booleans are digested here too
            m.update(
                value.to_bytes(
                    (value.bit_length() + 8) // 8, byteorder="little", signed=True
                )
            )
        case Digest():
            # Must precede str (Digest ⊂ str)
            return value.encode()
        case str():
            m.update(value.encode())
        case None:
            m.update(b"__None__")
        case Number():
            # Must follow int (int ⊂ Number).
            # lest we have nice things
            if cmath.isnan(value):
                # somehow hash(float('nan')) can yield different values even if having the same sign, because the
                # bespoke python hash special cases nan such that their location in memory is taken into account
                # apparently this is useful:
                # https://github.com/python/cpython/blob/1ac9d138ae0563f2829ba91efe7989af507f47e0/Python/pyhash.c#L59
                # because nans are not singletons this causes the code below to potentially assign different digests to
                # the same nan!  So in this case we revert back to just packing it into binary rep, because negative and
                # positive nans have different binary rep
                if isinstance(value, numbers.Complex):
                    m.update(struct.pack("<dd", value.real, value.imag))
                else:
                    m.update(struct.pack("<d", value))
                # on the other hand the IEEE standard does *not* assign a unique binary representation to NaN, but let's
                # burn that bridge when someone else tries to cross it.
                # the good news is that numpy nans seem to map to the same binary and are also detected by cmath.isnan
            else:
                # rely on python's 'generic' hash semantics for all numbers to translate all of them to an integer
                value = hash(value)
                # then digest its bytes
                return _digest_bytes(value)
        case bytes():
            m.update(value)
        case Path():
            # A *file* is identified by (basename, content): its name (and
            # extension) matter, but the content deduplicates.  A *directory* is
            # identified by its tree alone — its own (often incidental, e.g. a
            # temp dir) root name is dropped, though child names are kept.  Both
            # mirror exactly what PathValueMixin stores, preserving the
            # digest(path) == values.save(path) invariant on which cache lookups
            # of path-valued arguments/results depend.  The "FileBlob" /
            # "DirectoryBlob" salts MUST match
            # fleche.storage.paths.{FileBlob,DirectoryBlob}.__digest__.
            if not value.exists():
                raise Indigestible("Only existing paths can be digested.")
            if value.is_file():
                return _digest_bytes(
                    ("FileBlob", value.name, _path_content_digest(value))
                )
            elif value.is_dir():
                return _path_content_digest(value).encode()
            else:
                raise Indigestible("Can only digest files and folders!")
        case np.ndarray():
            m.update(_digest_bytes(value.dtype.str))
            m.update(_digest_bytes(value.shape))
            m.update(value.tobytes())
        case np.bool_():
            # np.bool_ ∉ Number so this arm is reachable
            return _digest_bytes(bool(value))
        case pd.DataFrame():
            # DataFrame is Iterable (yields column names) but NOT Mapping, so without
            # this arm two DataFrames sharing column names collide regardless of values.
            #
            # We digest columns/dtypes/index ourselves and pass index=False to
            # hash_pandas_object rather than letting index=True fold the index in.
            # hash_pandas_object only mixes per-element value bytes — it ignores
            # column names, column dtypes, index.name, and index.dtype — so
            # index=True alone would still collide DataFrames whose indices differ
            # only in name or dtype.  Recursing through _digest_bytes on
            # value.index also reuses the pd.Index arm below, keeping a standalone
            # Index and a DataFrame's .index digest-consistent.
            m.update(_digest_bytes(list(value.columns)))
            m.update(_digest_bytes([str(d) for d in value.dtypes]))
            m.update(_digest_bytes(value.index))
            m.update(pd.util.hash_pandas_object(value, index=False).values.tobytes())
        case pd.Series():
            # Same reasoning as DataFrame: hash_pandas_object ignores name/dtype/
            # index metadata, so we digest those ourselves and pass index=False.
            m.update(_digest_bytes(value.name))
            m.update(_digest_bytes(str(value.dtype)))
            m.update(_digest_bytes(value.index))
            m.update(pd.util.hash_pandas_object(value, index=False).values.tobytes())
        case pd.Index():
            m.update(_digest_bytes(value.name))
            m.update(_digest_bytes(str(value.dtype)))
            m.update(pd.util.hash_pandas_object(value).values.tobytes())
        case types.FunctionType():
            return _digest_bytes(value.__code__)
        case types.CodeType():
            # captured properties for behavior stability
            props = [
                value.co_code,
                value.co_consts,
                value.co_names,
                value.co_varnames,
                value.co_freevars,
                value.co_cellvars,
                value.co_argcount,
                value.co_posonlyargcount,
                value.co_kwonlyargcount,
                value.co_flags,
            ]
            if hasattr(value, "co_exceptiontable"):
                props.append(value.co_exceptiontable)
            m.update(_digest_bytes(tuple(props)))
        case datetime.timezone():
            m.update(_digest_bytes(value.utcoffset(None)))
        case datetime.timedelta():
            m.update(_digest_bytes(value.total_seconds()))
        case datetime.datetime():  # datetime subclasses date; must precede date case
            m.update(value.isoformat().encode())
        case datetime.date():
            m.update(value.isoformat().encode())
        case datetime.time():
            m.update(value.isoformat().encode())
        case staticmethod():
            m.update(_digest_bytes(value.__func__))
        case classmethod():
            m.update(_digest_bytes(value.__func__))
        case property():
            m.update(_digest_bytes((value.fget, value.fset, value.fdel)))
        case subprocess.CompletedProcess():
            m.update(
                _digest_bytes(
                    (value.args, value.returncode, value.stdout, value.stderr)
                )
            )
        case _ if isinstance(value, type) and value.__module__ == 'builtins':
            # Digest a built-in type (int, str, list, …) by its qualified name.
            # Restricted to the builtins module; user-defined types remain Indigestible.
            # This case must precede the dataclasses check: is_dataclass() returns True
            # for both a class and its instances, but getattr(cls, field) raises
            # AttributeError for required fields that have no class-level default.
            return _digest_bytes(f"builtins.{value.__qualname__}")
        case _ if dataclasses.is_dataclass(value) and not isinstance(value, type):
            # cannot use asdict because it recursively converts values which destroys digests
            # instead (flat-) convert to dictionaries, salt with type name, then fallback to dictionary case.
            fields = map(
                lambda f: (f.name, getattr(value, f.name)), dataclasses.fields(value)
            )
            m.update(_digest_bytes(dict(fields)))
        case _ if _attrs.is_attrs_instance(value):
            # mirror the dataclass digest format so an attrs class and a dataclass
            # with the same name + field layout hash identically.
            m.update(_digest_bytes(dict(_attrs.field_items(value))))
        case _ if isinstance(value, types.ModuleType):
            names = getattr(value, "__all__", None)
            if names is None:
                names = dir(value)
            _digest_mapping(m, {name: getattr(value, name) for name in names})
        case Mapping():
            _digest_mapping(m, dict(value))
        case Iterable():
            for v in value:
                m.update(_digest_bytes(v))
        case _:
            raise Indigestible(value)

    # To gain the raw-bytes speedup (Issue #440): change to m.digest() here,
    # update digest() to use .hex() instead of .decode(), and change the
    # encode()/bytes.fromhex() calls on the early-return paths above.
    return m.hexdigest().encode()
