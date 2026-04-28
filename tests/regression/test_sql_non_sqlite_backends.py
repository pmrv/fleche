"""Cross-dialect smoke + regression tests for the SQLAlchemy ``Sql`` backend.

The active-by-default suite already exercises the sqlite path. This file adds
a parametrized fixture (`external_sql`) that yields a ``Sql`` storage pointed
at a fresh database on every supported non-sqlite backend whose connection
URL was provided via environment variable. Tests are silently skipped when
no URL is configured, so the file is a no-op for default local runs but
becomes the cross-backend conformance suite under CI / when a developer
exports e.g. ``FLECHE_TEST_POSTGRES_URL``.

Why these specific assertions:
  * URL pass-through: regression for ``_coerce_sqlite_url`` rewriting any
    non-``sqlite:`` URL into a sqlite file path.
  * No PRAGMA on connect: regression for ``_enable_sqlite_foreign_keys``
    being registered unconditionally and crashing Postgres on the first
    connection.
  * Save / load / list / contains / evict: covers the backend's CRUD path
    against a real driver, which sqlite-only tests cannot do.
  * Query with metadata pushdown: exercises the JSON-extract path against
    each dialect's native JSON column type.
"""

import pytest

from fleche.call import Call, QueryCall
from fleche.digest import Digest
from fleche.storage.sql import Sql, _coerce_sqlite_url


# ---------------------------------------------------------------------------
# Fixture: parametrized over every configured non-sqlite backend
# ---------------------------------------------------------------------------
def _external_backends():
    """Return the list of param names whose URL env vars are set.

    Mirrors the dispatch in ``tests/fixtures.py`` so the param names line up.
    """
    import os

    backends = []
    if os.environ.get("FLECHE_TEST_POSTGRES_URL"):
        backends.append("postgres")
    if os.environ.get("FLECHE_TEST_MYSQL_URL"):
        backends.append("mysql")
    return backends


@pytest.fixture(params=_external_backends() or ["__skip__"])
def external_sql(request):
    """A fresh ``Sql`` backend on each configured non-sqlite database.

    The underlying ``postgres_sql`` / ``mysql_sql`` fixtures are themselves
    skip-when-unset, so we resolve only the one matching the current param
    via ``request.getfixturevalue`` — declaring both as direct dependencies
    would let the unconfigured one's skip cascade onto every test.
    """
    if request.param == "__skip__":
        pytest.skip(
            "No non-sqlite database URL configured "
            "(set FLECHE_TEST_POSTGRES_URL or FLECHE_TEST_MYSQL_URL)"
        )
    if request.param == "postgres":
        return request.getfixturevalue("postgres_sql")
    if request.param == "mysql":
        return request.getfixturevalue("mysql_sql")
    raise ValueError(f"Unknown external_sql param: {request.param}")


# ---------------------------------------------------------------------------
# URL pass-through (no live DB needed; runs always)
# ---------------------------------------------------------------------------
def test_postgres_url_passthrough():
    """A ``postgresql://`` URL must not be rewritten as a sqlite file path.

    Regression: the previous coercion treated any non-``sqlite:``-prefixed
    string as a filesystem path, so ``postgresql://host/db`` became
    ``sqlite:///<cwd>/postgresql:/host/db``.
    """
    url = "postgresql://user:pw@localhost:5432/some_db"
    assert _coerce_sqlite_url(url) == url


def test_mysql_url_passthrough():
    """A ``mysql+pymysql://`` URL must be returned verbatim."""
    url = "mysql+pymysql://user:pw@localhost:3306/some_db"
    assert _coerce_sqlite_url(url) == url


def test_postgres_url_passthrough_with_driver():
    """The dialect+driver form must also pass through unchanged."""
    url = "postgresql+psycopg2://localhost/db"
    assert _coerce_sqlite_url(url) == url


# ---------------------------------------------------------------------------
# Live, dialect-aware tests
# ---------------------------------------------------------------------------
def test_engine_dialect_is_not_sqlite(external_sql):
    """Sanity: the fixture wired up the right driver, not a fallback sqlite."""
    assert external_sql.engine.dialect.name in {"postgresql", "mysql", "mariadb"}


def test_save_load_roundtrip(external_sql):
    """Basic CRUD — argument digests, version, code_digest, result all
    round-trip through the non-sqlite backend.
    """
    call = Call(
        name="test_func",
        arguments={"a": Digest("a" * 64), "b": Digest("b" * 64)},
        metadata={"runtime": {"walltime": 1.5}},
        module="m",
        version=42,
        code_digest=Digest("c" * 64),
        result=Digest("r" * 64),
    )
    key = external_sql.save(call)

    loaded = external_sql.load(key)
    assert loaded.to_lookup_key() == call.to_lookup_key()
    assert loaded.name == "test_func"
    assert loaded.version == 42
    assert loaded.metadata == {"runtime": {"walltime": 1.5}}
    assert str(loaded.result) == "r" * 64


def test_contains_and_list(external_sql):
    """``contains`` and ``list`` must reflect what was just saved."""
    call = Call(
        name="f",
        arguments={"x": Digest("a" * 64)},
        metadata={},
        result=Digest("r" * 64),
    )
    key = external_sql.save(call)
    assert external_sql.contains(key)
    assert key in list(external_sql.list())


def test_evict_removes_call_and_arguments(external_sql):
    """Evicting a call must cascade to its arguments / metadata rows."""
    call = Call(
        name="f",
        arguments={"x": Digest("a" * 64)},
        metadata={"tags": {"phase": "train"}},
        result=Digest("r" * 64),
    )
    key = external_sql.save(call)
    assert external_sql.contains(key)
    external_sql.evict(key)
    assert not external_sql.contains(key)
    assert key not in list(external_sql.list())


def test_query_metadata_pushdown(external_sql):
    """JSON metadata filters must be pushed down through each dialect's
    native JSON column type and return the right call.
    """
    c1 = Call(
        name="f1",
        arguments={"a": Digest("a" * 64)},
        metadata={"flags": {"ok": True, "count": 3}},
        result=Digest("r" * 64),
    )
    c2 = Call(
        name="f2",
        arguments={"b": Digest("b" * 64)},
        metadata={"flags": {"ok": False, "count": 7}},
        result=Digest("s" * 64),
    )
    external_sql.save(c1)
    external_sql.save(c2)

    tpl = QueryCall(metadata={"flags": {"ok": True}})
    matched = list(external_sql.query(tpl))
    assert {c.name for c in matched} == {"f1"}


def test_query_argument_pushdown(external_sql):
    """Argument filters compared via ``digest()`` must work on each dialect."""
    c1 = Call(
        name="f", arguments={"a": Digest("a" * 64)}, metadata={}, result=None
    )
    c2 = Call(
        name="f", arguments={"a": Digest("b" * 64)}, metadata={}, result=None
    )
    external_sql.save(c1)
    external_sql.save(c2)

    tpl = QueryCall(arguments={"a": Digest("a" * 64)})
    matched = list(external_sql.query(tpl))
    assert {str(c.arguments["a"]) for c in matched} == {"a" * 64}


def test_overwrite_same_key(external_sql):
    """Saving twice with identical content must be a no-op (no duplicates)."""
    call = Call(
        name="f",
        arguments={"a": Digest("a" * 64)},
        metadata={},
        result=Digest("r" * 64),
    )
    k1 = external_sql.save(call)
    k2 = external_sql.save(call)
    assert k1 == k2
    assert sum(1 for _ in external_sql.list()) == 1
