"""Read the destructuring reference graph out of a serialised entry, without loading it.

:meth:`~fleche.storage.destructuring.DestructuringMixin.child_digests` answers
"which keys does this entry point at?" by deserialising the entry and
pattern-matching the :class:`~fleche.storage.destructuring.Digested` wrapper it
finds.  That works only while every class the payload mentions is importable —
which an archived cache, a cache written by someone else's project, or a cache
whose producing package has been uninstalled generally cannot promise.

The scanners here answer the same question straight off the serialised bytes.
Nothing is imported, no ``__reduce__`` is called, and the payload of a
non-destructured entry is never materialised at all.  Two formats are covered,
matching the two on-disk value backends:

- :func:`scan_pickle` walks the pickle opcode stream with :mod:`pickletools`,
  rebuilding *only* the container skeleton (lists, dicts, tuples, scalars) and
  representing every class as an inert :class:`_Global` name pair.
- :func:`scan_h5` walks a :mod:`bagofholding` HDF5 group, which stores the same
  skeleton as self-describing ``content_type``/``module``/``qualname``
  attributes.

Both are deliberately held to the *same* contract as
:meth:`~fleche.storage.destructuring.DestructuringMixin._raw_sub_digests`: the
direct :class:`~fleche.digest.Digest` children of a top-level built-in
``Digested`` wrapper, and nothing else.  An entry that is not one of those
wrappers has no children, exactly as on the load path.
"""

import pickletools
from dataclasses import dataclass
from typing import Any

from ..digest import Digest


class ScanUnsupported(Exception):
    """Raised when a storage cannot walk its reference graph without deserialising.

    Backends whose serialised form fleche cannot introspect (or which have no
    serialised form to introspect) raise this from
    ``scan_child_digests``/``count_reuses(load=False)``; the caller's fallback
    is the deserialising :meth:`~fleche.storage.destructuring.DestructuringMixin.child_digests`.
    """


# Recorded as (module, qualname) strings rather than classes: the whole point is
# to identify them in bytes written by a *different* interpreter, and matching by
# name means the scanners never import anything.  `tests/unit/storage/test_scan.py`
# pins these against the real classes so a rename cannot drift them apart.
_DIGEST_GLOBAL = ("fleche.digest", "Digest")
# Protocols 0 and 1 spell the stdlib helper with its Python-2 module name.
_RECONSTRUCTOR_GLOBALS = frozenset(
    {("copyreg", "_reconstructor"), ("copy_reg", "_reconstructor")}
)

_WRAPPER_SLOTS: "dict[tuple[str, str], str]" = {
    ("fleche.storage.destructuring", "DigestedIterable"): "items",
    ("fleche.storage.destructuring", "DigestedDict"): "items",
    ("fleche.storage.destructuring", "DigestedDataclass"): "fields",
    ("fleche.storage.destructuring", "DigestedAttrs"): "fields",
}
"""Wrapper class → the attribute holding its direct children.

Mirrors the ``match`` arms of
:meth:`~fleche.storage.destructuring.DestructuringMixin._raw_sub_digests`.
Third-party ``Digested`` subclasses defined outside fleche are not listed and
therefore scan as childless — the same blind spot the load path has for
anything that is not one of these three shapes.
"""


# --- shared -----------------------------------------------------------------


@dataclass(frozen=True)
class _Global:
    """A class or function *named* by the stream, never resolved to an object."""

    module: str
    name: str


@dataclass(frozen=True)
class _DigestRef:
    """A reconstructed :class:`~fleche.digest.Digest` — the thing we are hunting for."""

    value: str


@dataclass(eq=False)
class _Instance:
    """An object of some class, with whatever ``__setstate__`` payload it was given.

    ``eq=False`` keeps identity hashing, so an instance can sit in a rebuilt
    ``dict`` key position without raising.
    """

    cls: Any
    state: Any = None


class _Unknown:
    """Stand-in for a value the skeleton does not model (sets, buffers, extensions)."""

    __slots__ = ()

    def __repr__(self) -> str:
        return "<unknown>"


_UNKNOWN = _Unknown()


def _slot_digests(slot: Any) -> "set[Digest]":
    """Digests directly inside one wrapper slot (``items`` or ``fields``).

    Dict keys are scanned alongside values because
    :class:`~fleche.storage.destructuring.DigestedDict` interns both; the
    ``fields`` dict of a record wrapper only ever has ``str`` keys, so
    including them there is a no-op.
    """
    if isinstance(slot, dict):
        candidates: "list[Any]" = [*slot.keys(), *slot.values()]
    elif isinstance(slot, (list, tuple)):
        candidates = list(slot)
    else:
        return set()
    return {Digest(c.value) for c in candidates if isinstance(c, _DigestRef)}


def _wrapper_children(top: Any) -> "set[Digest]":
    """Direct digest children of *top*, or an empty set if it is not a wrapper."""
    if not isinstance(top, _Instance) or not isinstance(top.cls, _Global):
        return set()
    slot = _WRAPPER_SLOTS.get((top.cls.module, top.cls.name))
    if slot is None or not isinstance(top.state, dict):
        return set()
    return _slot_digests(top.state.get(slot))


# --- pickle -----------------------------------------------------------------


# Opcodes whose argument *is* the value they push.  The strings matter twice
# over: STACK_GLOBAL builds a class name out of two of them, and a Digest's
# whole payload is one.  The rest are carried along only so container positions
# line up.
_LITERAL_OPS = frozenset(
    {
        "STRING", "BINSTRING", "SHORT_BINSTRING",
        "UNICODE", "BINUNICODE", "SHORT_BINUNICODE", "BINUNICODE8",
        "INT", "BININT", "BININT1", "BININT2", "LONG", "LONG1", "LONG4",
        "FLOAT", "BINFLOAT",
        "BINBYTES", "SHORT_BINBYTES", "BINBYTES8", "BYTEARRAY8",
    }
)
_MEMO_PUT_OPS = frozenset({"PUT", "BINPUT", "LONG_BINPUT", "MEMOIZE"})
_MEMO_GET_OPS = frozenset({"GET", "BINGET", "LONG_BINGET"})

_MARK = object()


def scan_pickle(data: bytes) -> "set[Digest]":
    """Digest children of the pickled entry in *data*, without unpickling it.

    Args:
        data: the raw pickle stream, i.e. exactly what ``pickle.loads`` would
            be handed (already un-gzipped and stripped of any signature).

    Returns:
        The same set :meth:`~fleche.storage.destructuring.DestructuringMixin.child_digests`
        would return for this entry — empty when the entry is not a
        ``Digested`` wrapper.

    Raises:
        ValueError: if *data* is not a well-formed pickle stream.
        EOFError: if it is truncated — the same pair ``pickle.loads`` raises,
            since both come out of reading the opcode stream itself.
    """
    return _wrapper_children(_skeleton(data))


def _skeleton(data: bytes) -> Any:
    """Rebuild the pickle's container skeleton and return its top-level object.

    A cut-down unpickler machine: the stack effects are taken from
    :mod:`pickletools`' own opcode table (the same bookkeeping
    :func:`pickletools.dis` does to track MARK nesting), but the values pushed
    are inert — real containers and scalars where the stream spells them out,
    :class:`_Global` for every class reference, :class:`_Instance` for every
    object construction, and :data:`_UNKNOWN` for everything else.  No module
    is imported and no callable from the stream is ever invoked.
    """
    stack: "list[Any]" = []
    memo: "dict[Any, Any]" = {}
    top: Any = _UNKNOWN

    for op, arg, _pos in pickletools.genops(data):
        before, after = op.stack_before, op.stack_after
        numtopop = len(before)
        sliced: "list[Any]" = []

        takes_mark = pickletools.markobject in before
        if takes_mark or (op.name == "POP" and stack and stack[-1] is _MARK):
            index = _last_mark(stack)
            sliced = stack[index + 1:]
            del stack[index:]
            # Everything from the mark up is accounted for; `before` may still
            # name one operand *below* it (the list APPENDS extends, say).
            numtopop = before.index(pickletools.markobject) if takes_mark else 0

        if len(stack) < numtopop:
            # genops validates opcode encoding but not stack depth, so a corrupt
            # entry can ask for operands that were never pushed.  Fail as a
            # malformed stream rather than as an IndexError deeper in.
            raise ValueError(
                f"Malformed pickle: {op.name} pops {numtopop} items from a "
                f"stack holding {len(stack)}."
            )
        args = stack[len(stack) - numtopop:] if numtopop else []
        if numtopop:
            del stack[-numtopop:]

        if pickletools.markobject in after:
            stack.append(_MARK)
            continue
        if op.name == "STOP":
            top = args[0]
            break

        # The memo opcodes are the only ones that reach past their own operands:
        # the PUT family peeks at the stack top without declaring it, and MEMOIZE
        # pops and re-pushes it.  Both just record what is already there.
        if op.name in _MEMO_PUT_OPS:
            memoized = args[0] if args else (stack[-1] if stack else _UNKNOWN)
            memo[len(memo) if op.name == "MEMOIZE" else arg] = memoized
            stack.extend([memoized] * len(after))
            continue
        if op.name in _MEMO_GET_OPS:
            stack.append(memo.get(arg, _UNKNOWN))
            continue

        pushed = _apply(op.name, arg, args, sliced)
        if pushed is None:
            pushed = [_UNKNOWN] * len(after)
        stack.extend(pushed)

    return top


def _last_mark(stack: "list[Any]") -> int:
    for i in range(len(stack) - 1, -1, -1):
        if stack[i] is _MARK:
            return i
    raise ValueError("Malformed pickle: opcode expects a MARK that is not on the stack.")


def _apply(
    name: str, arg: Any, args: "list[Any]", sliced: "list[Any]"
) -> "list[Any] | None":
    """Stack effect of one opcode; ``None`` means "push opaque placeholders"."""
    if name in _LITERAL_OPS:
        return [arg]

    match name:
        case "PROTO" | "FRAME" | "POP" | "POP_MARK":
            return []
        case "NONE":
            return [None]
        case "NEWTRUE":
            return [True]
        case "NEWFALSE":
            return [False]
        case "DUP":
            return [args[0], args[0]]
        case "EMPTY_LIST":
            return [[]]
        case "EMPTY_DICT":
            return [{}]
        case "EMPTY_TUPLE":
            return [()]
        case "LIST":
            return [list(sliced)]
        case "TUPLE":
            return [tuple(sliced)]
        case "TUPLE1" | "TUPLE2" | "TUPLE3":
            return [tuple(args)]
        case "DICT":
            return [_rebuild_dict({}, sliced)]
        case "APPEND":
            return [_extend(args[0], args[1:])]
        case "APPENDS":
            return [_extend(args[0], sliced)]
        case "SETITEM":
            return [_rebuild_dict(args[0], args[1:])]
        case "SETITEMS":
            return [_rebuild_dict(args[0], sliced)]
        case "ADDITEMS":
            return [args[0]]
        case "GLOBAL":
            module, _, qualname = str(arg).partition(" ")
            return [_Global(module, qualname)]
        case "STACK_GLOBAL":
            module, qualname = args
            if isinstance(module, str) and isinstance(qualname, str):
                return [_Global(module, qualname)]
            return [_UNKNOWN]
        case "NEWOBJ" | "NEWOBJ_EX" | "REDUCE":
            return [_construct(args[0], args[1])]
        case "INST":  # protocol 0/1 `cls(*args)`; the class rides in the arg
            module, _, qualname = str(arg).partition(" ")
            return [_Instance(_Global(module, qualname))]
        case "OBJ":  # protocol 1 `cls(*args)`; the class is under the MARK
            return [_Instance(sliced[0]) if sliced else _UNKNOWN]
        case "BUILD":
            obj, state = args
            if isinstance(obj, _Instance):
                obj.state = state
            return [obj]
    return None


def _extend(container: Any, items: "list[Any]") -> Any:
    if isinstance(container, list):
        container.extend(items)
    return container


def _rebuild_dict(container: Any, flat: "list[Any]") -> Any:
    """Fold a flat ``[k, v, k, v, …]`` run into *container* if it is a dict."""
    if not isinstance(container, dict):
        return container
    for key, value in zip(flat[::2], flat[1::2]):
        try:
            container[key] = value
        except TypeError:  # unhashable skeleton key; not a slot we care about
            continue
    return container


def _construct(cls: Any, args: Any) -> Any:
    """Model ``cls(*args)`` without calling anything.

    The one construction that matters is a :class:`~fleche.digest.Digest`: as a
    ``str`` subclass it pickles as ``NEWOBJ(Digest, (value,))`` under protocol
    2+, and as ``copyreg._reconstructor(Digest, str, value)`` under the older
    protocols.  Everything else becomes an opaque instance whose class is only
    ever a name.
    """
    if isinstance(cls, _Global) and isinstance(args, tuple):
        named = (cls.module, cls.name)
        if named == _DIGEST_GLOBAL and len(args) == 1 and isinstance(args[0], str):
            return _DigestRef(args[0])
        if named in _RECONSTRUCTOR_GLOBALS and len(args) == 3:
            # _reconstructor(cls, base, state): the real class is the first
            # argument, so unwrap it or the instance would be attributed to the
            # stdlib helper instead.
            inner, _base, state = args
            if isinstance(inner, _Global):
                if (inner.module, inner.name) == _DIGEST_GLOBAL and isinstance(state, str):
                    return _DigestRef(state)
                return _Instance(inner)
    return _Instance(cls)


# --- bagofholding / HDF5 ----------------------------------------------------


_H5_SEQUENCE = frozenset({"bagofholding.content.List", "bagofholding.content.Tuple"})
_H5_DICT = "bagofholding.content.Dict"
_H5_STR_KEY_DICT = "bagofholding.content.StrKeyDict"


def scan_h5(entry: Any) -> "set[Digest]":
    """Digest children of one bagofholding bag, without loading it.

    A bag stores the object graph as nested HDF5 groups tagged with
    ``content_type``/``module``/``qualname`` attributes, so the skeleton is
    already on disk in readable form — this walks three levels of it
    (``object`` → ``state`` → the wrapper's slot) and reads the digest strings
    out of the ``Digest`` reducibles it finds.

    Args:
        entry: the open :class:`h5py.Group` holding one stored value — the
            file root in per-key layout, or the ``file.h5/{key}`` group in
            multi-bag layout.  Duck-typed, so no :mod:`h5py` import is needed
            here.

    Returns:
        The same set :meth:`~fleche.storage.destructuring.DestructuringMixin.child_digests`
        would return for this entry — empty when the entry is not a
        ``Digested`` wrapper.
    """
    obj = entry.get("object")
    if obj is None:
        return set()
    slot = _WRAPPER_SLOTS.get((obj.attrs.get("module"), obj.attrs.get("qualname")))
    if slot is None:
        return set()
    state = obj.get("state")
    if state is None:
        return set()
    node = state.get(slot)
    if node is None:
        return set()
    return {
        found
        for child in _h5_children(node)
        if (found := _h5_digest(child)) is not None
    }


def _h5_children(node: Any) -> "list[Any]":
    """The element nodes of a bagged container, whatever container it is."""
    content_type = node.attrs.get("content_type")
    if content_type in _H5_SEQUENCE or content_type == _H5_STR_KEY_DICT:
        # Sequences are `i0`…`iN`, str-keyed dicts are their keys; a str key can
        # never be a Digest reducible, so iterating both the same way is safe.
        return [node[name] for name in node.keys()]
    if content_type == _H5_DICT:
        # General dicts split into parallel `keys`/`values` tuples, and
        # DigestedDict interns both sides.
        return [
            part[name]
            for part in (node.get("keys"), node.get("values"))
            if part is not None
            for name in part.keys()
        ]
    return []


def _h5_digest(node: Any) -> "Digest | None":
    """The digest string of a bagged ``Digest``, or ``None`` for anything else."""
    attrs = node.attrs
    if (attrs.get("module"), attrs.get("qualname")) != _DIGEST_GLOBAL:
        return None
    args = node.get("args")
    # Reduced as `Digest.__new__(Digest, value)`: args/i0 is the class, i1 the string.
    value = None if args is None else args.get("i1")
    if value is None:
        return None
    raw = value[()]
    return Digest(raw.decode() if isinstance(raw, bytes) else str(raw))
