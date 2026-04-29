Developer Guide
===============

This page collects notes that aren't relevant to end users of ``fleche`` but
are useful when hacking on the library itself.

.. _testing-non-sqlite-backends:

Testing the SQL backend on non-sqlite dialects
----------------------------------------------

The ``Sql`` :class:`~fleche.storage.sql.Sql` ``CallStorage`` is implemented on
top of SQLAlchemy and is portable to any dialect SQLAlchemy supports. By
default the test suite only exercises the sqlite path, because that is the
only backend with no out-of-process dependencies. The cross-dialect tests are
opt-in: they activate when a connection URL is supplied via environment
variable, and skip silently otherwise.

Two environment variables are recognised:

============================== ====================================================
Variable                       Example value
============================== ====================================================
``FLECHE_TEST_POSTGRES_URL``   ``postgresql+psycopg2://fleche:fleche@localhost:5432/postgres``
``FLECHE_TEST_MYSQL_URL``      ``mysql+pymysql://fleche:fleche@localhost:3306/mysql``
============================== ====================================================

The URL must point at a server (the database part of the URL is the
*administrative* database used to mint per-test databases — typically
``postgres`` for PostgreSQL, ``mysql`` for MySQL/MariaDB). The connecting role
needs ``CREATE DATABASE`` privilege.

When set, the test session:

1. Adds ``sql_postgres`` / ``sql_mysql`` parametrizations to the shared
   ``call_storage`` fixture, so any test consuming that fixture (e.g. the
   pickle round-trip suite) sweeps over the new backends as well.
2. Activates the ``postgres_sql`` / ``mysql_sql`` single-shot fixtures and the
   parametrized ``external_sql`` fixture used by
   ``tests/regression/test_sql_non_sqlite_backends.py`` for backend-targeted
   regression tests.

Each test gets a freshly created, uniquely named database that is dropped on
teardown — so concurrent tests don't share schema state and there's nothing
to clean up after a test crash beyond the next ``DROP DATABASE`` attempt.

Running locally
~~~~~~~~~~~~~~~

A typical local cycle against PostgreSQL looks like:

.. code-block:: bash

   # Once: create a role with CREATE DATABASE privilege.
   sudo -u postgres psql -c \
       "CREATE USER fleche WITH PASSWORD 'fleche' CREATEDB;"

   # Per session: point the suite at the running server.
   export FLECHE_TEST_POSTGRES_URL=postgresql+psycopg2://fleche:fleche@localhost:5432/postgres
   pip install psycopg2-binary

   pytest tests/regression/test_sql_non_sqlite_backends.py
   # ... or sweep every consumer of call_storage:
   pytest tests/

For MariaDB / MySQL the workflow is symmetric:

.. code-block:: bash

   sudo mysql -e \
       "CREATE USER 'fleche'@'localhost' IDENTIFIED BY 'fleche';
        GRANT ALL PRIVILEGES ON *.* TO 'fleche'@'localhost' WITH GRANT OPTION;"

   export FLECHE_TEST_MYSQL_URL=mysql+pymysql://fleche:fleche@localhost:3306/mysql
   pip install pymysql

   pytest tests/regression/test_sql_non_sqlite_backends.py

Continuous integration
~~~~~~~~~~~~~~~~~~~~~~

The ``sql-backends`` job in ``.github/workflows/tests.yml`` provisions
``postgres:16`` and ``mariadb:11`` service containers, exports the
corresponding env vars, and installs the dialect drivers (``psycopg2-binary``,
``pymysql``) before invoking ``pytest``. The drivers are kept out of the
project's ``[tests]`` extra on purpose — they are only needed by maintainers
running the cross-dialect suite, not by end users.

Adding a new SQL dialect
~~~~~~~~~~~~~~~~~~~~~~~~

The fixture machinery in ``tests/fixtures.py`` is small enough to extend
in-place:

1. Pick a new env var name and a new param identifier.
2. Add a branch to ``_admin_url`` if the dialect requires connecting to a
   specific administrative database (Postgres needs ``postgres``).
3. If the dialect's identifier quoting differs further from the
   ``identifier_preparer`` defaults, special-case it; otherwise the existing
   ``CREATE DATABASE``/``DROP DATABASE`` paths will work.
4. Append the new param to ``_call_storage_params`` so existing
   ``call_storage`` consumers sweep it automatically.

The schema in :mod:`fleche.storage.sql` already uses ``String().with_variant``
so dialect-specific length requirements (MySQL needs ``VARCHAR`` lengths) stay
contained to the affected dialect — no other dialect should be perturbed when
adding a new one.
