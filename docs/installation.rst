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
* ``fleche`` -- the full install, which also pulls in the optional dependencies.

.. code-block:: bash

   # Core library only
   conda install -c conda-forge fleche-base

   # Full install with all optional dependencies
   conda install -c conda-forge fleche

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
