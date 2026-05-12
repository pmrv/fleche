Developer Guide
===============

This page collects notes that aren't relevant to end users of ``fleche`` but
are useful when hacking on the library itself.

.. _function-profile:

Per-function metadata: ``FunctionProfile``
------------------------------------------

All static per-function metadata is consolidated in the frozen dataclass
:class:`~fleche.call.FunctionProfile` (defined in :mod:`fleche.call`).  The
class method ``FunctionProfile.of(func)`` performs every introspection step
in one place:

- ``inspect.signature`` for argument binding and ``Required`` positional-only
  checks
- ``pyiron_snippets.versions.VersionInfo`` for ``qualname``, ``module``, and
  ``version``
- ``func.__code__`` hashing (``code_digest``)
- ``get_type_hints(include_extras=True)`` to detect ``Ignored`` /
  ``Required`` annotations (populates ``ignored`` / ``required`` fields)

The result is stored by ``_profile``, a module-level
``lru_cache(maxsize=1000)`` keyed on the callable's identity.  Indigestible
callables fall back to ``_profile.__wrapped__`` (bypassing the LRU cache) so
they are handled correctly without special-casing at call sites.

**Adding new per-function metadata** is a two-step operation: add a field to
``FunctionProfile`` and populate it inside ``FunctionProfile.of``.  Downstream
code then reads it from the profile instead of calling introspection APIs
directly.

.. _extending-destructurer:

Extending the destructurer
--------------------------

The ``DestructuringMixin`` type-dispatch table, ``_DESTRUCTURERS``, is a
module-level list of ``(predicate, sunder_fn)`` pairs.  It ships with four
built-in entries — lists/tuples, dicts, dataclasses, and attrs instances — and
can be extended at import time via
:func:`~fleche.storage.destructuring.register_destructurer`.

.. warning::

   ``_DESTRUCTURERS`` is a global, mutable list.  Every
   :class:`~fleche.storage.destructuring.DestructuringMixin` instance shares it.
   Registering a destructurer after storage instances have already been used
   produces undefined behaviour because ``_intern_rec`` closes over the list
   state at call time.

Before reaching for this function, consider whether implementing
``__digest__`` (or ``add_hook``) on the type in question is sufficient.
Destructurer registration is only necessary when a container type must have
its *children* stored as independent, reusable keys rather than being pickled
as a single opaque blob.

**Contract for** ``sunder_fn``

The function must have the signature ``(intern, value) -> (result, depth)``
where:

- ``intern`` is :meth:`~fleche.storage.destructuring.DestructuringMixin._intern_rec`
  — call it on each child value and collect the returned ``(child, depth)``
  pairs.
- ``result`` must be either the plain value (when all children are inlined,
  i.e. no child returned a :class:`~fleche.digest.Digest`) or a new
  :class:`~fleche.storage.destructuring.Digested` subclass instance wrapping
  the children.
- ``depth`` must be ``1 + max(child_depths)`` when children were processed,
  or ``float("inf")`` when the value cannot be handled.

The ``Digested`` subclass must implement :meth:`~fleche.storage.destructuring.Digested.mend`
(reconstruction from storage), :meth:`~fleche.storage.destructuring.Digested.underlying`
(for hashing), and the class-method
:meth:`~fleche.storage.destructuring.Digested.sunder` (the ``sunder_fn``
itself, as a classmethod).  Study
:class:`~fleche.storage.destructuring.DigestedIterable` or
:class:`~fleche.storage.destructuring.DigestedDict` as the canonical
reference implementations before writing your own.

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
