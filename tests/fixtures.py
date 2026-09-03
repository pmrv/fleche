import functools
import os
import threading
import uuid
from contextlib import contextmanager

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine.url import make_url

from fleche.storage import (
    ValueMemory,
    CallMemory,
    ValuePickleFile,
    CallPickleFile,
    ValueBagOfHoldingH5File,
    CallBagOfHoldingH5File,
    Sql,
)
from fleche.storage.memory import MemoryBackend
from fleche.storage.pickle_file import PickleFileBackend
from fleche.storage.bagofholding_file import BagOfHoldingH5FileBackend
from fleche.caches import Cache

secret_key = [b"test_secret_key_32_bytes_long!!!!"]


# ---------------------------------------------------------------------------
# Concurrency stress-test helper
#
# Many thread-safety tests share the same shape: spawn N threads, have each do
# some work, collect any exceptions, join, and assert nothing blew up. This
# helper collapses that boilerplate so the tests only describe the work.
# ---------------------------------------------------------------------------

def run_workers(worker, count=None, *, timeout=None):
    """Run worker callables concurrently in threads; return captured exceptions.

    Exceptions raised in any worker are captured (thread-safely) and returned as
    a list, so callers just ``assert not run_workers(...)`` instead of repeating
    the spawn/start/join/collect dance by hand.

    Two calling forms:

    * ``run_workers(fn, n)`` spawns ``n`` threads; thread ``i`` calls ``fn(i)``.
    * ``run_workers([fn0, fn1, ...])`` spawns one thread per callable, each
      invoked with no arguments. Use this for heterogeneous worker mixes (e.g.
      some readers + some writers); bind per-worker arguments with
      ``functools.partial``.

    ``timeout`` is forwarded to each ``Thread.join``.
    """
    if count is not None:
        workers = [functools.partial(worker, i) for i in range(count)]
    else:
        workers = list(worker)

    errors: list[Exception] = []
    errors_lock = threading.Lock()

    def run(fn):
        try:
            fn()
        except Exception as exc:  # noqa: BLE001 — surfaced to the caller via `errors`
            with errors_lock:
                errors.append(exc)

    threads = [threading.Thread(target=run, args=(fn,)) for fn in workers]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout)
    return errors


# ---------------------------------------------------------------------------
# Non-sqlite SQLAlchemy backend support
#
# We don't bundle any out-of-process database; instead, the corresponding
# fixtures activate only when a connection URL is provided via environment
# variable, and each test gets a freshly-created database for full isolation.
# ---------------------------------------------------------------------------
POSTGRES_URL_ENV = "FLECHE_TEST_POSTGRES_URL"
MYSQL_URL_ENV = "FLECHE_TEST_MYSQL_URL"


def _admin_url(url):
    """Return a copy of ``url`` connected to the server's admin database.

    Postgres requires connecting to *some* database to run ``CREATE DATABASE``;
    we use the conventional ``postgres`` database. MySQL/MariaDB doesn't need a
    selected database, so we drop the database name entirely.
    """
    backend = url.get_backend_name()
    if backend == "postgresql":
        return url.set(database="postgres")
    return url.set(database=None)


@contextmanager
def _ephemeral_database(base_url: str):
    """Create a uniquely-named database for one test, then drop it.

    Yields the URL string a fleche ``Sql`` backend can be pointed at.
    """
    url = make_url(base_url)
    backend = url.get_backend_name()
    db_name = f"fleche_test_{uuid.uuid4().hex}"

    admin_url = _admin_url(url)
    admin_engine = create_engine(
        admin_url, isolation_level="AUTOCOMMIT", future=True
    )
    # Use the dialect's own identifier preparer so MySQL/MariaDB get backticks
    # and Postgres gets double quotes — bare double quotes are a syntax error
    # on MariaDB unless ANSI_QUOTES is enabled.
    quoted_db = admin_engine.dialect.identifier_preparer.quote(db_name)
    try:
        with admin_engine.connect() as conn:
            conn.execute(text(f"CREATE DATABASE {quoted_db}"))
    finally:
        admin_engine.dispose()

    test_url = url.set(database=db_name).render_as_string(hide_password=False)
    try:
        yield test_url
    finally:
        admin_engine = create_engine(
            admin_url, isolation_level="AUTOCOMMIT", future=True
        )
        quoted_db = admin_engine.dialect.identifier_preparer.quote(db_name)
        try:
            with admin_engine.connect() as conn:
                if backend == "postgresql":
                    # Force-disconnect any leftover sessions or DROP DATABASE
                    # blocks until they idle out.
                    conn.execute(
                        text(
                            "SELECT pg_terminate_backend(pid) "
                            "FROM pg_stat_activity "
                            "WHERE datname = :db AND pid <> pg_backend_pid()"
                        ),
                        {"db": db_name},
                    )
                conn.execute(text(f"DROP DATABASE {quoted_db}"))
        finally:
            admin_engine.dispose()


def _make_external_sql(env_var: str):
    """Yield a ``Sql`` backend pointed at a fresh DB, or skip."""
    base = os.environ.get(env_var)
    if not base:
        pytest.skip(f"{env_var} not set; non-sqlite SQL backend test skipped")
    with _ephemeral_database(base) as url:
        sql = Sql(url)
        try:
            yield sql
        finally:
            sql.engine.dispose()


VALUE_STORAGE_PARAMS = ["memory", "cloudpickle", "dill", "pickle", "h5", "h5_multi"]


def _call_storage_params():
    """Build the parametrization list for ``call_storage``.

    Always-on backends are listed first; non-sqlite SQL backends are only
    appended when their URL env var is set, so local default runs stay quiet.
    """
    params = ["memory", "cloudpickle", "dill", "pickle", "h5", "h5_multi", "sql"]
    if os.environ.get(POSTGRES_URL_ENV):
        params.append("sql_postgres")
    if os.environ.get(MYSQL_URL_ENV):
        params.append("sql_mysql")
    return params


def _build_value_storage(param, tmp_path):
    if param == "memory":
        return ValueMemory({})
    elif param == "cloudpickle":
        return ValuePickleFile.with_cloudpickle(
            tmp_path / "cloudpickle", secret_key=secret_key
        )
    elif param == "dill":
        return ValuePickleFile.with_dill(tmp_path / "dill", secret_key=secret_key)
    elif param == "pickle":
        return ValuePickleFile.with_pickle(tmp_path / "pickle", secret_key=secret_key)
    elif param == "h5":
        return ValueBagOfHoldingH5File(tmp_path / "h5", prefix_length=None)
    elif param == "h5_multi":
        return ValueBagOfHoldingH5File(tmp_path / "h5_multi", prefix_length=2)
    else:
        raise ValueError(f"Unknown value_storage param: {param}")


@contextmanager
def _build_call_storage(param, tmp_path):
    """Yield one call storage; a context manager because the external-SQL
    params own a database that has to be dropped again."""
    if param == "memory":
        yield CallMemory({})
    elif param == "cloudpickle":
        yield CallPickleFile.with_cloudpickle(
            tmp_path / "cloudpickle", secret_key=secret_key
        )
    elif param == "dill":
        yield CallPickleFile.with_dill(tmp_path / "dill", secret_key=secret_key)
    elif param == "pickle":
        yield CallPickleFile.with_pickle(tmp_path / "pickle", secret_key=secret_key)
    elif param == "h5":
        yield CallBagOfHoldingH5File(tmp_path / "h5", prefix_length=None)
    elif param == "h5_multi":
        yield CallBagOfHoldingH5File(tmp_path / "h5_multi", prefix_length=2)
    elif param == "sql":
        yield Sql(tmp_path / "calls.db")
    elif param == "sql_postgres":
        yield from _make_external_sql(POSTGRES_URL_ENV)
    elif param == "sql_mysql":
        yield from _make_external_sql(MYSQL_URL_ENV)
    else:
        raise ValueError(f"Unknown call_storage param: {param}")


@pytest.fixture(params=_call_storage_params())
def call_storage(request, tmp_path):
    with _build_call_storage(request.param, tmp_path) as storage:
        yield storage


@pytest.fixture(params=VALUE_STORAGE_PARAMS)
def value_storage(request, tmp_path):
    return _build_value_storage(request.param, tmp_path)


def _paired_storage_params():
    """Pair the value- and call-storage sweeps along a diagonal.

    Requesting ``value_storage`` and ``call_storage`` in the same test takes
    their Cartesian product (42 cases locally, 54 in the SQL-backends CI job).
    Where the test only needs *a* cache per backend rather than every
    combination of two independent halves, this walks both lists in step
    instead, cycling the shorter one, so every backend on either side still
    appears at least once for a case count of ``max(len(values), len(calls))``.
    """
    values, calls = VALUE_STORAGE_PARAMS, _call_storage_params()
    return [
        (values[i % len(values)], calls[i % len(calls)])
        for i in range(max(len(values), len(calls)))
    ]


@pytest.fixture(
    params=_paired_storage_params(),
    ids=[f"{v}-{c}" for v, c in _paired_storage_params()],
)
def paired_storages(request, tmp_path):
    """``(value_storage, call_storage)`` swept diagonally rather than crosswise."""
    value_param, call_param = request.param
    value = _build_value_storage(value_param, tmp_path)
    with _build_call_storage(call_param, tmp_path) as call:
        yield value, call

@pytest.fixture(params=["memory", "cloudpickle", "dill", "pickle", "h5", "h5_multi"])
def storage_backend(request, tmp_path):
    if request.param == "memory":
        return MemoryBackend({})
    elif request.param == "cloudpickle":
        return PickleFileBackend.with_cloudpickle(tmp_path / "cloudpickle")
    elif request.param == "dill":
        return PickleFileBackend.with_dill(tmp_path / "dill")
    elif request.param == "pickle":
        return PickleFileBackend.with_pickle(tmp_path / "pickle")
    elif request.param == "h5":
        return BagOfHoldingH5FileBackend(tmp_path / "h5", prefix_length=None)
    elif request.param == "h5_multi":
        return BagOfHoldingH5FileBackend(tmp_path / "h5_multi", prefix_length=2)


@pytest.fixture
def postgres_sql():
    """A ``Sql`` storage pointed at a freshly-created Postgres database.

    Skipped unless ``FLECHE_TEST_POSTGRES_URL`` is set (e.g.
    ``postgresql+psycopg2://user:pw@localhost:5432/postgres``). The fixture
    creates a unique per-test database and drops it on teardown.
    """
    yield from _make_external_sql(POSTGRES_URL_ENV)


@pytest.fixture
def mysql_sql():
    """A ``Sql`` storage pointed at a freshly-created MySQL/MariaDB database.

    Skipped unless ``FLECHE_TEST_MYSQL_URL`` is set (e.g.
    ``mysql+pymysql://user:pw@localhost:3306/mysql``). The fixture creates
    a unique per-test database and drops it on teardown.
    """
    yield from _make_external_sql(MYSQL_URL_ENV)


@pytest.fixture
def clean_cache():
    yield Cache(ValueMemory({}), CallMemory({}))


@pytest.fixture
def file_cache(tmp_path):
    yield Cache(
        ValuePickleFile.with_pickle(root=tmp_path / "values"),
        CallPickleFile.with_pickle(root=tmp_path / "calls"),
    )
