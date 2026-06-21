Path Storage Internals
======================

How ``fleche`` stores :class:`~pathlib.Path` values — single files and whole
directory trees — by content.  For the practical version, see
:doc:`/recipes/files_and_paths`.

The model, in one line
----------------------

``fleche`` follows git's split: **content is content-addressed; names live in
trees.**  Concretely —

* a **file** is identified by ``(basename, content)`` — its name matters, its
  bytes deduplicate;
* a **directory** is identified by its **tree alone** — child names are part of
  it, but the directory's own root name is not (a reloaded directory is named by
  its digest);
* plain **bytes** are anonymous file content — return them when you don't want a
  name to enter the cache key.

:class:`~fleche.storage.paths.PathValueMixin` owns the traversal.  In the default
value storages it sits between ``DestructuringMixin`` and ``ValueMixin`` in the
method-resolution order, so a bare ``Path`` (or one nested inside a list, dict,
or dataclass) is intercepted on save and materialized again on load.

How a file is stored
--------------------

A file is split into two pieces so that content deduplicates while the name is
still part of the key:

* the bytes are saved as **plain** ``bytes`` under their content digest — shared
  by every file (and every ``bytes`` value) with the same content;
* a small :class:`~fleche.storage.paths.FileBlob` record pairs the basename with
  a *reference* to that content blob, and is keyed
  ``digest(("FileBlob", name, content_digest))``.

On load the content is materialized at ``<tempdir>/<name>`` and returned as an
ordinary path, so ``.name`` / ``.suffix`` / ``.stem`` are faithful and a consumer
needs no special-casing.  Because the bytes live in a shared, content-keyed blob
and only the tiny ``FileBlob`` differs per name, **renaming a file never
duplicates its body** — a rename adds one record and reuses the blob.

How a directory is stored
-------------------------

A directory is a :class:`~fleche.storage.paths.DirectoryBlob`: a
``{name: content_ref}`` mapping keyed by ``digest(("DirectoryBlob", contents))``.
A file child is referenced by its content bytes; a subdirectory child by its own
``DirectoryBlob``.  The directory's **own** name never enters this — two trees
with identical contents under different root names hash identically.  On load the
tree is rebuilt under ``<tempdir>/<digest>`` (hashed root, faithful children).

The ``digest(path) == values.save(path)`` invariant
---------------------------------------------------

This is the load-bearing property.  ``fleche`` *looks up* a cached call by
``digest(arguments)`` but *stores* it under ``values.save(arguments)``; the two
must agree, or a call that takes or returns a path would never hit.  The ``Path``
arm of :func:`~fleche.digest.digest` therefore mirrors storage exactly — a file
as ``digest(("FileBlob", name, digest(bytes)))``, a directory as the content-only
tree — with the ``"FileBlob"`` / ``"DirectoryBlob"`` salts matching
:class:`~fleche.storage.paths.FileBlob` and
:class:`~fleche.storage.paths.DirectoryBlob`'s ``__digest__``.

Deduplication
-------------

Everything bottoms out in content-keyed ``bytes`` blobs, so an identical body is
stored once — across names, across directories, and across plain ``bytes``
values.  Only the small ``FileBlob`` / ``DirectoryBlob`` records (references, not
bytes) differ.

Salting (the tuple idiom)
-------------------------

``FileBlob`` and ``DirectoryBlob`` salt their digests with the class name via the
tuple idiom from :doc:`custom_digests`.  This keeps a ``DirectoryBlob`` from
colliding with a plain ``dict`` carrying the same ``{name: digest}`` mapping, and
a ``FileBlob`` record from colliding with an unrelated value of the same shape.
Note that file *content* needs no such marker: it is plain ``bytes``, and the
"this is a file" information lives in the ``FileBlob`` record (top level) or the
parent ``DirectoryBlob`` entry (inside a tree), never in the content blob itself.

Choosing content-only
---------------------

There is no separate "anonymous path" type: if you want a file's content without
its name in the key, return the ``bytes``.  There is deliberately no way to make
a *directory's* root name significant — directories are trees, and their root
name is treated as incidental (typically a temp dir).  If a root name carries
meaning, name a *child* meaningfully instead, or wrap the tree's identity in your
own value.

See also
--------

* :doc:`/recipes/files_and_paths` — copy-paste recipes.
* :doc:`/notebooks/Files` — a runnable walkthrough.
* :doc:`custom_digests` — the tuple-digest idiom these blobs use.
