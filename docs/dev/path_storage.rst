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

Why ``remaining_depth`` cannot reach a path
-------------------------------------------

``PathValueMixin`` only ever sees a value that
:class:`~fleche.storage.destructuring.DestructuringMixin` decided to **write
out** — an inlined value is carried inside its parent's ``Digested`` wrapper and
pickled with it, never handed down the MRO.  So "a nested path is always stored
by content" holds only if a path can never be inlined, and that is arranged
rather than hoped for: a ``Path`` matches no destructurer, so ``_intern_rec``
leaves its depth at ``float("inf")``, and ``inf < remaining_depth`` is false for
every setting.

That is the enforcement mechanism, not a side effect of one.  It also
propagates, since a parent's depth is ``1 + max(child_depths)``: every container
between the root and a path inherits ``inf`` and is written out as its own
entry too.  Sibling subtrees are untouched and inline exactly as they would
without the path.

``[[[1, 2], [3, path]], [4, 5]]`` at ``remaining_depth=10`` — a setting that
collapses the same structure without the path into a *single* entry:

.. code-block:: text

   bytes             b'xyz'
   FileBlob          FileBlob('data.txt', <bytes digest>)
   DigestedIterable  [3, <FileBlob digest>]          <- innermost, own entry
   DigestedIterable  [[1, 2], <digest>]              <- own entry; [1, 2] inlined
   DigestedIterable  [<digest>, [4, 5]]              <- root;      [4, 5] inlined

So one path costs *its own nesting depth* in extra entries, not the size of the
structure around it, and the scalars beside it inline under the usual rules
(``[1, 3, 4, path]`` stores as ``DigestedIterable([1, 3, 4, <digest>])``, not as
four separate slots).  Tuning ``remaining_depth`` for a path-heavy workload
therefore changes how the *non-path* parts are packed and nothing else — the
content addressing of the paths is not on the table.

Blobs must declare their references
-----------------------------------

Storing a path by content splits it in two: the ``bytes`` live under their own
content digest, and the :class:`~fleche.storage.paths.FileBlob` /
:class:`~fleche.storage.paths.DirectoryBlob` record holds a *reference* to
them.  That makes the blob a node in the value store's reference graph, and
anything walking that graph — :meth:`~fleche.caches.Cache.gc`,
:meth:`~fleche.storage.destructuring.DestructuringMixin.count_reuses` — has to
be told so.  A blob that reports no children looks like a leaf, its content
looks unreferenced, and ``gc`` reclaims the bytes out from under it; the entry
survives as a record pointing at nothing, and the next load raises
``KeyError``, which the wrapper reports as an ordinary cache miss.  Silent data
loss, triggered by routine maintenance.

:meth:`PathValueMixin._raw_sub_digests` therefore declares them, and each
mixin that wraps values in a record of its own does the same for its own
wrappers, delegating anything it does not recognise down the MRO — so a
storage's reachable set is the union over its layers rather than whichever
layer happens to answer first.

The walk reads through :meth:`~fleche.storage.base.ValueStorage.load_raw`
rather than ``load``, for two reasons.  Correctness: ``load`` mends, and
mending resolves child references away — a materialized ``Path`` no longer
knows which blob it came from.  Cost: mending a stored path means copying its
whole tree into a temp directory, so a graph walk through ``load`` would
rebuild every stored file on disk purely to ask what it points at.

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

Why paths stop at the SSH boundary
----------------------------------

:class:`~fleche.remote.SshCache` is the one cache where "store this path"
cannot mean what it means everywhere else, because the two sides do not share
a filesystem.  Values cross the wire by cloudpickle, and a pickled ``Path`` is
only its string — so a path handed to the remote is a *name it resolves
itself*.  Three things follow, and each of them is silent:

* ``save_value`` on the remote runs :class:`PathValueMixin` against the
  **server's** disk.  If a file happens to sit at that name it is stored, under
  the digest of *those* bytes; ``digest(path) == values.save(path)`` — the
  invariant the seal in :meth:`~fleche.caches.BaseCache.prepare` rests on —
  is broken, and the record lands under a key no client ever recomputes.
* if nothing sits there, the server raises ``Indigestible`` from the middle of
  an RPC.
* ``load_value`` materializes into a temp directory on the **server** and can
  only ship the name back.  The :class:`TempPath` guard does not survive the
  hop either — ``PurePath.__reduce__`` reconstructs from ``parts`` alone, so
  the ``_temp_root`` attribute is dropped and the class-level ``_live_roots``
  registry is per-process — so the server frees the tree as soon as its own
  reference dies, and the client is left with a dangling name for a filesystem
  it cannot see.

So :class:`~fleche.remote.SshCache` refuses instead, via
:func:`~fleche.storage.paths.find_path` (which walks a value exactly the way a
destructuring save does, using
:func:`~fleche.storage.destructuring.child_slots`) and
:class:`~fleche.remote.RemotePathUnsupported`.  That exception subclasses
:class:`~fleche.storage.SaveError` so the existing two-phase-save degradations
carry it: a path argument becomes a digest-only reference **whose digest was
computed locally**, which keeps the seal intact and lookups correct, and a path
result becomes :class:`~fleche.caches.Rejected`, so the call runs uncached
rather than wrongly cached.

The degradation is deliberately per *argument*, not per call.  ``prepare`` is
the one RPC that carries argument values rather than digests, so a call
carrying a path cannot be shipped whole; it stashes the arguments one at a
time through :class:`~fleche.remote._RemoteValues` instead, and
:meth:`~fleche.call.Call.stash`'s existing per-argument ``SaveError`` fallback
does the rest — only the path arguments are digested-and-not-stored, and their
siblings are stored and remain loadable off the record.  Falling back to the
blanket digest-only admission instead would cost every other argument for the
sake of one path, which is neither what the guard promises nor necessary.  See :ref:`file-remote-caches` for the user-facing
version.

Making paths genuinely work over SSH is a separate feature, tracked in
`issue #829 <https://github.com/pmrv/fleche/issues/829>`_.  The shape is
already visible above: :meth:`PathValueMixin.save` reduces a path to ``bytes``
plus a :class:`FileBlob` / :class:`DirectoryBlob`, all of which ship fine, and
those blobs' ``__digest__`` is *defined* to match the ``Path`` arm — so running
the reduction **client-side** keeps the seal intact by construction.  The one
new piece is on the load side: an unmended ``load_value`` that hands back the
blob instead of materializing it on the server, so the client materializes into
its own temp directory and owns the :class:`TempPath` lifetime.  That is a
change to the RPC surface, not to this module.

See also
--------

* :doc:`/usage/file_semantics` — the user-facing contract this implements.
* :doc:`/recipes/files_and_paths` — copy-paste recipes.
* :doc:`/notebooks/Files` — a runnable walkthrough.
* :doc:`custom_digests` — the tuple-digest idiom these blobs use.
