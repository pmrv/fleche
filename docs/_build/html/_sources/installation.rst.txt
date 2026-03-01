Installation Guide
==================

Normal installation
-------------------

.. code-block:: bash

   pip install fleche

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
