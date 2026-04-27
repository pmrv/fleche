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
