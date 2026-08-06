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

Arguments are keyed **as passed** — captured before the body runs — and a
mutation the body performs on one is neither recorded nor replayed.  That is
a general rule (:ref:`argument-mutation`); its most common instance here is a
function that writes an output file *into* a directory it received.  The call
is recorded under the directory's pre-call tree, so honest repeat calls hit,
but the written file does not reappear on a hit — it exists only on cold
calls.

Returning what you wrote to is the normal shape, not a workaround for this: a
function that writes into a directory and hands that directory back is recorded
with it in its final, post-mutation state, and that is the intended way to
produce files.  What is not replayed is a write to something you never return —
so a path that is pure *input* should be treated as read-only, with new files
written somewhere you do return (``tempfile.mkdtemp``).

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

Whether a nested path is stored by content comes down to one thing:
**destructuring** — whether storage takes the surrounding container apart into
independently-stored children, or pickles it whole as one opaque value.  Only
children reach the path machinery, so the list of containers fleche
destructures *is* the list of places a nested path gets content treatment.
That list is
:data:`~fleche.storage.destructuring._DESTRUCTURERS`: ``dict``,
``OrderedDict``, ``list``, ``tuple`` (**exact types** — see below),
``dataclasses`` and ``attrs`` classes.  See :ref:`extending-destructurer` for
the mechanism and how to add your own container to it.

Within those, paths are found nested to any depth, as values *or* as dict
keys, and everything above about identity, materialization, and lifetime
applies to each one individually.  Container structure is otherwise faithful
on a hit: lists and tuples keep their element order, and a mended dict keeps
the insertion order the stored value had.

"Any depth" is not a figure of speech, and no storage setting narrows it.  A
``Path`` matches no destructurer, so it is always written out as its own stored
entry rather than inlined into the container above it — and being written out is
exactly what hands it to the content machinery.  The
``remaining_depth`` knob only decides how eagerly *destructurable* nodes are
split into separate entries, so it cannot put a path out of reach however it is
set.

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
object) is never destructured out of it, and so never reaches the content
machinery.  The call is still *keyed*
correctly — the digest layer does look inside — but what is stored is the path
object itself, pointing at wherever the file was when it was saved.  A hit
returns that original *location* (whether as the same object or an equal copy
is backend-dependent — rely on neither): if the file has since been deleted or
edited, the hit hands you a dangling or stale path, **without any warning**.

Rule of thumb: return paths in plain dicts / lists / tuples / dataclasses.  If
you need a custom container to participate, register a destructurer for it
with :func:`~fleche.storage.destructuring.register_destructurer` — see
:ref:`extending-destructurer`.

.. _file-dedup:

Deduplication
-------------

File bodies are stored once per unique byte-content — shared across file
names, across directories, and with plain ``bytes`` values.  Renaming a file
and re-caching adds a tiny name record, never a second copy of the bytes.  If
you want *keys* (not just storage) to ignore the name too, return ``bytes``
instead of a ``Path``; that is the content-only escape hatch.

.. _file-remote-caches:

Paths stop at a remote (SSH) cache
----------------------------------

Everything above assumes the cache and your process see the **same
filesystem**.  A :class:`~fleche.remote.SshCache` does not: it forwards each
operation to a fleche running on another machine, and values travel by
cloudpickle — which reduces a ``Path`` to its *string*.  Only the name would
arrive, and the remote would resolve it against its own filesystem, storing
whatever happens to sit there (or nothing) under a digest that no longer
matches yours.

Rather than store something else under your key, fleche refuses:
:class:`~fleche.remote.RemotePathUnsupported` is raised when a path — bare or
nested in a container — would cross the wire.  Because it is a
:class:`~fleche.storage.SaveError`, the usual degradations apply and your code
does not have to catch anything:

* a path **argument** falls back to a digest-only reference.  The call is still
  keyed correctly (the digest is computed *here*, from your file), so lookups
  hit and miss exactly as they should; only the file's bytes are not retrievable
  from the remote record.
* a path **result** is rejected: the call runs, returns your file, and is
  logged as not cached.
* **loading** a path stored on the remote raises too.  The remote materializes
  into a temp directory on *its* disk and can only send back the name, which
  means nothing here.  This is lazy — a record whose result is a path can still
  be loaded and queried; only touching the path value raises.

To share file content across machines, return the file's ``bytes``: they
travel and deduplicate normally.  To keep full path semantics, put a local
cache layer in front of the remote one (see :doc:`/notebooks/CacheStack`) — the
local layer is where saves land, so paths never reach the wire.

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
Return a ``Path`` through an ``SshCache``        Refused: runs, warns, not cached
===============================================  ======================================

See also
--------

* :doc:`/recipes/files_and_paths` — copy-paste recipes.
* :doc:`/dev/path_storage` — how storage implements this contract.
* :doc:`/digests/digests_as_args` — passing digests instead of values.
