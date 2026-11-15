.. _sql-server:

Sharing calls through a database server
=======================================

The ``sql`` call storage works with any database SQLAlchemy can reach, not
just SQLite.  A PostgreSQL or MariaDB server is the better call index when
many processes, possibly on several machines, write to one cache at the same
time: SQLite serializes writers through file locks, and those are slow or
unreliable on network filesystems.

Only the call records go to the server.  Values still need a value storage
every process can reach, typically a ``pickle``/``cloudpickle`` root on a
shared filesystem.

fleche does not run the server for you.  Start it yourself (below, or ask
whoever runs your cluster) and point ``calls.url`` at it.

Drivers
-------

Install SQLAlchemy and the driver for your server, and name the driver in the
URL::

    pip install "fleche[sqlalchemy]" psycopg2-binary   # PostgreSQL
    pip install "fleche[sqlalchemy]" pymysql           # MariaDB / MySQL

=============  ==========================================
Server         URL scheme
=============  ==========================================
PostgreSQL     ``postgresql+psycopg2://...``
MariaDB/MySQL  ``mysql+pymysql://...``
=============  ==========================================

Spell the driver out: since SQLAlchemy 2.1 a bare ``postgresql://`` selects
psycopg 3 (the ``psycopg`` package), not ``psycopg2``.

Starting a server without root
------------------------------

Both servers run fine as an ordinary user, with the data directory in your
home directory.  The binaries come from your distribution (on Debian/Ubuntu
the PostgreSQL ones live in ``/usr/lib/postgresql/<version>/bin``, which is
not on ``PATH``) or from conda-forge's ``postgresql`` package.

PostgreSQL:

.. code-block:: bash

   initdb -D ~/fleche-db -U fleche --auth=scram-sha-256 --pwprompt
   pg_ctl -D ~/fleche-db -l ~/fleche-db.log \
       -o "-p 5433 -c listen_addresses=127.0.0.1 -k ''" start
   createdb -h 127.0.0.1 -p 5433 -U fleche fleche
   # ...
   pg_ctl -D ~/fleche-db stop -m fast

``-k ''`` turns off the Unix socket, whose default directory is usually not
writable by ordinary users.

MariaDB:

.. code-block:: bash

   mariadb-install-db --no-defaults --datadir=$HOME/fleche-mariadb \
       --auth-root-authentication-method=socket --skip-test-db
   mariadbd --no-defaults --datadir=$HOME/fleche-mariadb \
       --bind-address=127.0.0.1 --port=3307 --socket=$HOME/mariadb.sock &
   mariadb --no-defaults --socket=$HOME/mariadb.sock -e "
       CREATE DATABASE fleche;
       CREATE USER 'fleche'@'%' IDENTIFIED BY '<password>';
       GRANT ALL ON fleche.* TO 'fleche'@'%';"
   # ...
   mariadb-admin --no-defaults --socket=$HOME/mariadb.sock shutdown

``--no-defaults`` keeps the system-wide ``/etc/mysql`` configuration, whose
paths an ordinary user cannot write, out of the way.

Keeping the password out of ``fleche.toml``
-------------------------------------------

``fleche.toml`` is often committed or readable by others, so put the
connection details in your client's own credential file (mode ``600``) and
leave only a reference in the config.

PostgreSQL reads a `service file
<https://www.postgresql.org/docs/current/libpq-pgservice.html>`_ and a
`password file <https://www.postgresql.org/docs/current/libpq-pgpass.html>`_:

.. code-block:: ini

   # ~/.pg_service.conf
   [fleche]
   host=127.0.0.1
   port=5433
   dbname=fleche
   user=fleche

.. code-block:: text

   # ~/.pgpass  (chmod 600)
   127.0.0.1:5433:fleche:fleche:<password>

.. code-block:: toml

   [shared]
   values.type = "cloudpickle"
   values.root = "/shared/project/values"
   calls.type = "sql"
   calls.url = "postgresql+psycopg2:///?service=fleche"

MariaDB reads an option file through ``pymysql``'s ``read_default_file``
(``~`` is expanded):

.. code-block:: ini

   # ~/.my.cnf  (chmod 600)
   [client]
   host=127.0.0.1
   port=3307
   user=fleche
   password=<password>

.. code-block:: toml

   [shared]
   values.type = "cloudpickle"
   values.root = "/shared/project/values"
   calls.type = "sql"
   calls.url = "mysql+pymysql:///fleche?read_default_file=~/.my.cnf"

Either way, moving the server to another host or port only means editing the
credential file; the shared ``fleche.toml`` stays the same.

Several machines
----------------

To reach the server from other machines, listen on a routable address and
allow those clients in:

* PostgreSQL: start with ``-c listen_addresses='*'`` (or the host's address)
  and add a line to ``~/fleche-db/pg_hba.conf`` such as
  ``host fleche fleche 10.0.0.0/8 scram-sha-256``.
* MariaDB: start with ``--bind-address=0.0.0.0``.

Then put the server's host name in each client's credential file.

Operational notes
-----------------

These come from running a central PostgreSQL index on a Slurm cluster
(`#1047 <https://github.com/pmrv/fleche/issues/1047>`_ has the full report):

* Keep the data directory on a local or home filesystem.  PostgreSQL refuses
  to start when the directory's permissions are wider than its owner's, which
  network filesystems that force group bits (setgid) impose.
* Never start two servers on the same data directory.
* In a batch job, have the scheduler signal the job well before its time
  limit and stop the server cleanly from a trap, e.g. ``pg_ctl stop -m fast``.
* Throughput is usually limited by the value storage, not the call index:
  keep values off filesystems that are slow at creating many small files.

Known limitations
-----------------

* If the server is unreachable, every cached call raises SQLAlchemy's
  ``OperationalError``; nothing is computed in its place.
* When concurrent workers compute *the same* call, some of them can see an
  ``IntegrityError`` raised from the decorated function, although the stored
  record is correct.

Both are tracked in `#1047 <https://github.com/pmrv/fleche/issues/1047>`_.  Concurrent workers opening an empty
database at once, and MariaDB deadlocks between concurrent writers, are
handled: ``Sql`` retries schema creation and deadlocked transactions.
