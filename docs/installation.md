# Installation Guide

## Normal installation

```bash
pip install fleche
```

## Installing documentation (optional)

The documentation relies on a few extra packages.  They are provided as an optional
extra named `docs`.  To install them together with the library you can run:

```bash
pip install "fleche[docs]"
```

If you are developing the project in an editable checkout, use:

```bash
pip install -e .[docs]
```

## Building the docs locally

Once the optional dependencies are installed you can serve the documentation
locally with:

```bash
mkdocs serve
```

Open <http://127.0.0.1:8000> in a browser to view the site.
