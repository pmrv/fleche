File and Path Semantics
=======================

What happens, precisely, when a :class:`~pathlib.Path` crosses the cache
boundary — as an argument, as a return value, or nested inside one.  This page
is the contract: everything here is intended behavior you may rely on.  For
copy-paste recipes see :doc:`/recipes/files_and_paths`; for the storage design
see :doc:`/dev/path_storage`.

The model in three sentences
----------------------------

A **file** is identified by its ``(basename, content)`` — where it lives never
matters, what it is called and what is in it always do.  A **directory** is
identified by its tree alone — child names and contents, recursively — while its
own root name is ignored.  A cache hit does not give you back the original
location: it **materializes a fresh copy** under a temporary directory and hands
you the path to that.

Identity: what makes two calls "the same call"
----------------------------------------------

Arguments are turned into a lookup key by digesting them; for paths the digest
follows the model above.

* ``f(Path("a/data.csv"))`` and ``f(Path("b/data.csv"))`` are the **same call**
  if both files have the same bytes — location is not part of the key.
* ``f(Path("data.csv"))`` and ``f(Path("data.tsv"))`` are **different calls**
  even with identical bytes — the basename is part of a file's key.
* Editing a file's content changes the key: the next call is a miss and
  recomputes.
* For a **directory** argument, renaming or moving the directory itself does
  *not* change the key, but renaming or moving anything **inside** it does.
* ``bytes`` arguments are content-keyed too: two calls passing equal bytes are
  the same call, regardless of where the bytes came from.
* Two distinct arguments whose digests agree are interchangeable: a hit can be
  served for a path argument your process never saw before, as long as name and
  bytes match.

The same identity governs return values: results are stored by content, so two
functions returning identical files share one stored body (see
:ref:`file-dedup`).

Argument mutation
~~~~~~~~~~~~~~~~~

A call is keyed on its arguments **as passed**: argument content is captured
*before* the function body runs.  A function that mutates its own argument —
most commonly, writing an output file *into* a directory it received — is
still recorded under the pre-call content, so honest repeat calls hit.  The
mutation itself, however, is neither recorded nor replayed: a cache hit
leaves the argument untouched, so a side effect on the input happens on cold
calls only.

fleche caches *pure* functions.  What a function does to its arguments
without passing it back out is invisible to the cache — treat received paths
as read-only and write outputs to a fresh directory (``tempfile.mkdtemp``).
A mutated argument that *is* returned is captured faithfully in its final,
post-mutation state: if the mutation is the point, return it.

Only *content* changes count as mutation: permissions are not part of
identity (see :ref:`fidelity-limits`), so a ``chmod`` on a received path is
harmless.

Nonexistent paths
~~~~~~~~~~~~~~~~~

A path that does not exist on disk has no content and therefore **no digest**.
Passing one to a cached function does not raise: fleche logs a warning
(``"No hash for argument: ..."``) and **runs the function uncached** — every
call executes, nothing is stored or looked up.  If you meant "an output
location the function should write to", pass the location as a ``str`` or
annotate the parameter :class:`~fleche.Ignored` (``dest: Ignored[Path]``) so it
stays out of the key.

Cache hits materialize copies
-----------------------------

On a hit, fleche rebuilds the file (or tree) from stored content in a **fresh
temporary directory** and returns that path.  Consequences you should design
for:

* **The location changes.**  The cold (computing) call returns the function's
  return value untouched — same objects, same locations, same aliasing; every
  subsequent hit returns a path under a new temporary directory.  Never
  compare returned paths by location or store ``str(path)`` as a stable
  identifier.
* **The type changes.**  Hits return a ``Path`` subclass that manages the
  temporary tree's lifetime.  The subclass is an implementation detail — do not
  import it or dispatch on its name; rely only on ``isinstance(p, Path)``, and
  do not assume ``type(p) is PosixPath``.
* **File names are faithful.**  A file materializes as ``<tmp>/<basename>``:
  ``.name``, ``.suffix``, and ``.stem`` are the same cold and warm.
* **Directory root names are not.**  A directory materializes as
  ``<tmp>/<digest>``: its own ``.name`` is a hex digest on a hit.  The digest
  name is deterministic — hits for the same content always carry the same root
  name (under differing temporary parents) — but treat it as opaque.
  Everything *inside* — child names, nesting, contents — is faithful.
* **Every hit is a fresh copy.**  Each hit materializes under its own private
  temporary directory, so two hits for the same call return two different
  locations with equal content.  For large files this means disk traffic per
  hit; hold on to the result rather than re-calling in a loop.
* **Siblings do not come along.**  Only the returned (or passed) path is
  captured.  A hit's ``p.parent`` contains nothing but ``p`` itself — code
  like ``p.parent / "meta.json"`` works on the cold call and fails on hits.
  Return the sibling too, or return the whole directory.
* **The original is not needed.**  Once stored, hits are served from cache
  content; the file the cold call returned can be deleted, moved, or edited
  without affecting later hits.

.. _fidelity-limits:

Fidelity limits
~~~~~~~~~~~~~~~

What is stored — and thus what a hit restores — is **names and bytes, nothing
else**:

* **Permissions are not preserved.**  A materialized file has default
  permissions; in particular the executable bit is lost, so a returned script
  is not runnable on a hit without a fresh ``chmod``.  (Permissions are also
  not part of identity: ``chmod`` alone never changes a key.)
* **Symlinks are flattened.**  A symlink inside a returned directory is stored
  and restored as an ordinary file with the *target's* content.
* **Empty subdirectories are preserved**; modification times, ownership, and
  other metadata are not.

Lifetime of materialized paths
------------------------------

The temporary tree behind a hit lives exactly as long as some ``Path`` object
derived from it is referenced.  Deriving (``p.parent``, ``p / "x"``,
``p.with_suffix(...)``) keeps the tree alive; converting to ``str`` does not.

.. code-block:: python

   p = cached_fn()          # hit -> temp file
   loc = str(p)
   del p                    # last reference gone ...
   Path(loc).exists()       # ... False: the temp tree was deleted

Keep the ``Path`` object (or the container holding it) for as long as you need
the file.  If you need the file at a stable location, copy it out:
``shutil.copy(p, dest)``.

Paths nested inside containers
------------------------------

Paths are found and content-stored inside the containers fleche takes apart:
``dict``, ``OrderedDict``, ``list``, ``tuple`` (**exact types** — see below),
``dataclasses`` and ``attrs`` classes — nested to any depth, as values *or* as
dict keys.  Everything above about identity, materialization, and lifetime
applies to each nested path individually.  Container structure is otherwise
faithful on a hit: lists and tuples keep their element order, and a mended
dict keeps the insertion order the stored value had.

Three caveats specific to nesting:

* **Dict keys mend into new keys.**  A ``Path`` used as a dictionary key comes
  back as a materialized path at a new location — keys get the same
  materialization, type, and lifetime treatment as values — and looking the
  entry up by the *original* path object misses (``Path`` hashing is
  location-based).  If you intend to look entries up, key by something that
  survives a round trip: the basename (``path.name``) or an
  application-level identifier.
* **Aliasing is not preserved.**  If the same path object appears twice in a
  result, a hit materializes each occurrence separately: equal content, two
  locations, ``is``-distinct objects.
* **Only listed container types are traversed.**  Subclasses — including
  ``defaultdict``, ``Counter``, and ``namedtuple`` — and other containers
  (``set``, plain classes that are not dataclass/attrs) are stored **verbatim**
  as opaque values.

Opaque containers store paths by *location*
-------------------------------------------

A path inside an opaque value (a ``namedtuple``, a ``set``, an arbitrary
object) never reaches the content machinery.  The call is still *keyed*
correctly — the digest layer does look inside — but what is stored is the path
object itself, pointing at wherever the file was when it was saved.  A hit
returns that original *location* (whether as the same object or an equal copy
is backend-dependent — rely on neither): if the file has since been deleted or
edited, the hit hands you a dangling or stale path, **without any warning**.

Rule of thumb: return paths in plain dicts / lists / tuples / dataclasses.  If
you need a custom container to participate, see
:func:`~fleche.storage.destructuring.register_destructurer`.

.. _file-dedup:

Deduplication
-------------

File bodies are stored once per unique byte-content — shared across file
names, across directories, and with plain ``bytes`` values.  Renaming a file
and re-caching adds a tiny name record, never a second copy of the bytes.  If
you want *keys* (not just storage) to ignore the name too, return ``bytes``
instead of a ``Path``; that is the content-only escape hatch.

Quick reference
---------------

===============================================  ======================================
You do                                           A cache hit gives you
===============================================  ======================================
Return ``Path`` to a file                        Copy at ``<tmp>/<same basename>``
Return ``Path`` to a directory                   Tree at ``<tmp>/<digest>``, faithful inside
Return paths in dict/list/tuple/dataclass        Same container shape, each path a copy
Return ``bytes``                                 The bytes (no file, no name)
Use ``Path`` as dict key                         New key at new location
Return same path twice                           Two independent copies
Return path inside namedtuple/set/custom class   The *original* location (may be stale)
Pass a nonexistent ``Path`` argument             No caching: warns, always executes
Write into a directory you received              Hit (keyed as passed); write not replayed
===============================================  ======================================

See also
--------

* :doc:`/recipes/files_and_paths` — copy-paste recipes.
* :doc:`/dev/path_storage` — how storage implements this contract.
* :doc:`/digests/digests_as_args` — passing digests instead of values.
