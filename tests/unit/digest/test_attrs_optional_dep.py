"""``fleche._attrs`` when the optional ``attrs`` package is not installed.

``_attrs`` is the only optional-dependency shim outside ``fleche.storage``
(whose backends are covered by ``tests/unit/storage/test_optional_deps.py``),
and its promise is the opposite of theirs: a missing *backend* dependency
raises at construction, while a missing ``attrs`` must degrade *silently*.
``is_attrs_instance`` returning ``False`` is what makes the ``case _ if
_attrs.is_attrs_instance(value)`` guard in :func:`fleche.digest.digest` and the
destructurer predicate in ``fleche.storage.destructuring`` fall through to
their generic paths instead of raising ``AttributeError`` on a ``None`` module.

No CI job exercises that: the ``tests`` extra requires ``attrs``, so ``import
attr`` always succeeds — including in the minimum-deps job. The path only
exists if it is simulated, so this test masks ``attr`` in ``sys.modules`` and
reimports ``fleche._attrs`` from source, the same idiom
``tests/unit/storage/test_optional_deps.py`` uses. It deliberately does *not*
``importorskip("attr")``: the behaviour under test is the no-``attrs`` install,
which is exactly where a skip would hide it.
"""

import importlib
import sys
from unittest.mock import patch

import pytest


@pytest.fixture
def attrs_shim_without_attr():
    """A fresh ``fleche._attrs`` imported with ``import attr`` failing.

    The reimported module is a distinct object from the one
    ``fleche.digest`` / ``fleche.storage.destructuring`` already hold, so
    nothing outside this test sees the degraded shim; the original is put
    back in ``sys.modules`` on the way out.
    """
    original = sys.modules.pop("fleche._attrs", None)
    try:
        with patch.dict(sys.modules, {"attr": None}):
            yield importlib.import_module("fleche._attrs")
    finally:
        sys.modules.pop("fleche._attrs", None)
        if original is not None:
            sys.modules["fleche._attrs"] = original


def test_is_attrs_instance_is_false_when_attrs_is_missing(attrs_shim_without_attr):
    """Without ``attrs``, the type check answers ``False`` rather than raising."""
    shim = attrs_shim_without_attr

    # Guard: without this the test would still pass against a shim that
    # imported attrs successfully, since a plain object is not an attrs
    # instance either.
    assert shim._attr is None

    assert shim.is_attrs_instance(object()) is False
