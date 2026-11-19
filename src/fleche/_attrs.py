"""Internal helpers for hashing and destructuring ``attrs``-decorated classes.

The ``attrs`` package is an optional dependency; importing this module is always safe.
Helpers gracefully degrade (``is_attrs_instance`` returns ``False``, ``field_items``
asserts) when ``attr`` cannot be imported.
"""

import types
from typing import Any

try:
    import attr as _attr_module
    _attr: types.ModuleType | None = _attr_module
except ImportError:
    _attr = None


def _synthesized_pickle_code() -> frozenset[types.CodeType]:
    """Code objects of the ``__getstate__``/``__setstate__`` attrs writes for slotted classes.

    attrs builds them as per-class closures over one function, so they share a code
    object; that is how a hook attrs generated is told apart from one a user wrote.
    They read and write exactly the attrs fields, so they say nothing a field walk does not.
    """
    if _attr is None:
        return frozenset()

    @_attr.define
    class _SlottedProbe:
        x: int = 0

    hooks = (getattr(_SlottedProbe, name, None) for name in ("__getstate__", "__setstate__"))
    return frozenset(
        code for code in (getattr(hook, "__code__", None) for hook in hooks) if code is not None
    )


SYNTHESIZED_PICKLE_CODE = _synthesized_pickle_code()


def is_attrs_instance(value: Any) -> bool:
    """Return True iff *value* is an instance of an ``attrs``-decorated class.

    Returns False (rather than raising) when ``attrs`` is not installed.
    """
    return (
        _attr is not None
        and not isinstance(value, type)
        and _attr.has(type(value))
    )


def field_items(value: Any) -> list[tuple[str, Any]]:
    """Return ``[(name, value), ...]`` for every attribute of an attrs instance."""
    assert _attr is not None
    return [(f.name, getattr(value, f.name)) for f in _attr.fields(type(value))]
