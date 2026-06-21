Caching Functions that Work with Files
======================================

Short, copy-paste recipes for caching functions that produce or consume files
and directories.  For *why* any of this works, see :doc:`/dev/path_storage`; for
a runnable walkthrough, see the :doc:`/notebooks/Files` notebook.

Return a file from a cached function
------------------------------------

Just return the :class:`~pathlib.Path`.  ``fleche`` stores the file's *contents*
(not the path string), keyed on its ``(name, content)`` — so the cache is
portable across machines, and a cache hit comes back as a path with the **same
name and extension**.

.. code-block:: python

   from pathlib import Path
   from fleche import fleche

   @fleche
   def render(text) -> Path:
       out = Path("report.pdf")
       out.write_text(text)
       return out

Downstream code needs nothing special — a cache hit is an ordinary ``Path``:

.. code-block:: python

   @fleche
   def count_pages(doc: Path) -> int:
       assert doc.suffix == ".pdf"     # still true on a cache hit
       return ...

   count_pages(render("hello"))

Don't care about the name? Return ``bytes``
-------------------------------------------

If the filename is irrelevant and you only care about the content, return the
``bytes`` instead of a ``Path``.  Content-only values deduplicate maximally —
the same bytes under different would-be names share one cache entry.

.. code-block:: python

   @fleche
   def serialize(obj) -> bytes:
       return pickle.dumps(obj)

Return a directory
------------------

Return the directory ``Path``; the whole tree round-trips, and its children keep
their names.

.. code-block:: python

   @fleche
   def build(src) -> Path:
       out = Path("build")
       out.mkdir()
       (out / "result.bin").write_bytes(compile(src))
       return out

.. note::

   A directory is identified by its *tree*, not its root name — so a reloaded
   directory's own ``.name`` is a hash (its children's names are faithful).
   Don't rely on the top-level directory name surviving a cache hit; do rely on
   everything inside it.
