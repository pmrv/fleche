Installation Guide
==================

Normal installation
-------------------

.. code-block:: bash

   pip install fleche

Installing with conda
---------------------

``fleche`` is also available on `conda-forge <https://conda-forge.org/>`_. Two
packages are published:

* ``fleche-base`` -- the core library only (no optional dependencies).
* ``fleche`` -- the full install, which also pulls in the optional dependencies
  (``cloudpickle``, ``dill``, ``sqlalchemy`` and ``bagofholding``), enabling the
  SQL, SSH, alternate-serialization and Bagofholding features out of the box.

.. code-block:: bash

   # Core library only
   conda install -c conda-forge fleche-base

   # Full install with all optional dependencies
   conda install -c conda-forge fleche

Optional dependencies
---------------------

The core install is deliberately lean. Extra features are gated behind optional
dependencies, exposed as pip *extras*. Install one or more by listing them in
brackets, e.g. ``pip install "fleche[sqlalchemy,ssh]"``.

.. list-table::
   :header-rows: 1
   :widths: 18 30 52

   * - Extra
     - Install
     - Enables
   * - ``cloudpickle``
     - ``pip install "fleche[cloudpickle]"``
     - The ``cloudpickle`` serializer for the file backend
       (``PickleFileBackend.with_cloudpickle``); also the wire protocol used by
       SSH caches.
   * - ``dill``
     - ``pip install "fleche[dill]"``
     - The ``dill`` serializer for the file backend
       (``PickleFileBackend.with_dill``).
   * - ``sqlalchemy``
     - ``pip install "fleche[sqlalchemy]"``
     - The SQL call-storage backend (``type = "sql"``) via SQLAlchemy --
       SQLite, PostgreSQL, MySQL and any other SQLAlchemy-supported database.
   * - ``bagofholding``
     - ``pip install "fleche[bagofholding]"``
     - The HDF5 storage backend (``type = "bagofholding_hdf"``).
   * - ``ssh``
     - ``pip install "fleche[ssh]"``
     - :class:`~fleche.remote.SshCache`, which forwards a whole cache to a
       remote host over SSH. Pulls in ``cloudpickle`` (its wire protocol), so
       it is required rather than optional.
   * - ``executorlib``
     - ``pip install "fleche[executorlib]"``
     - Running cached calls through `executorlib
       <https://executorlib.readthedocs.io/>`_ executors for cluster/parallel
       execution (see :doc:`parallel_execution`).
   * - ``docs``
     - ``pip install "fleche[docs]"``
     - The packages needed to build this documentation (see below).
   * - ``tests``
     - ``pip install "fleche[tests]"``
     - The full test suite plus every optional backend it exercises.

.. note::

   The conda-forge ``fleche`` metapackage covers the ``cloudpickle``, ``dill``,
   ``sqlalchemy``, ``bagofholding`` and ``ssh`` features in one install. The
   ``executorlib``, ``docs`` and ``tests`` extras are pip-only -- install
   ``executorlib`` from conda-forge separately if you need it.

Installing documentation (optional)
-----------------------------------

The documentation relies on a few extra packages. They are provided as an optional
extra named ``docs``. To install them together with the library you can run:

.. code-block:: bash

   pip install "fleche[docs]"

If you are developing the project in an editable checkout, use:

.. code-block:: bash

   pip install -e .[docs]

Building the docs locally
-------------------------

Once the optional dependencies are installed you can build the documentation
locally with:

.. code-block:: bash

   sphinx-build -b html docs/ docs/_build/html

Open ``docs/_build/html/index.html`` in a browser to view the site.
