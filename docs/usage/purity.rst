.. _purity:

Purity and Side Effects
=======================

What fleche assumes about the functions you decorate, and what therefore does
*not* survive a cache hit.  The rules here apply to every argument and result
type; :doc:`file_semantics` is the same contract seen through ``Path`` values.

The assumption
--------------

fleche caches **pure** functions: the result is determined by the arguments,
and anything else the body does is incidental.  A cache hit replays the
*result* and nothing else — so every effect a function has besides returning
a value happens on cold calls only.

That is not a restriction fleche can check, and it does not raise if you break
it.  It shows up as a function that behaves differently the second time you
call it.

.. _argument-mutation:

Arguments are keyed as passed
-----------------------------

Argument content is captured **before** the body runs, so a function that
mutates its own argument is still recorded under the pre-call content and
honest repeat calls hit.  The mutation itself is neither recorded nor
replayed:

.. code-block:: python

   @fleche
   def append_and_report(xs, n):
       xs.append(n)
       return len(xs)

   a = [1, 2]
   append_and_report(a, 9)   # 3 — body runs, and a is now [1, 2, 9]

   b = [1, 2]
   append_and_report(b, 9)   # 3 — cache hit; b is still [1, 2]

Both calls return ``3``, because that is the recorded result.  Only the first
one changed its argument.  Nothing about this is specific to lists: a
``dict``, a numpy array, and a directory a function writes into all behave the
same way.

Return what you mutate
~~~~~~~~~~~~~~~~~~~~~~

An argument that is mutated **and returned** is captured faithfully in its
final, post-mutation state — the result is stored after the body runs:

.. code-block:: python

   @fleche
   def append_and_return(xs, n):
       xs.append(n)
       return xs

   append_and_return([1, 2], 9)   # [1, 2, 9] — body runs
   append_and_return([1, 2], 9)   # [1, 2, 9] — cache hit, same value

If the mutation is the point of the function, return it.  Treat arguments you
receive as read-only otherwise, and build results fresh.

Other side effects
------------------

Everything else a body does — printing, logging, writing files outside the
returned value, sending a request, inserting a row — happens on the cold call
and never again:

.. code-block:: python

   @fleche
   def record(x):
       db.insert(x)        # runs once, ever
       return x * 2

If an effect must happen on every call, it belongs outside the cached
function; keep the cached part to the computation whose result you want
stored.

Two related cases
-----------------

* A function returning ``None`` is never cached, so it re-executes every time
  — including its side effects.  See :ref:`none-not-cached`.
* Paths follow all of the above, with the mutation case made concrete:
  a directory a function receives and writes into is recorded under its
  pre-call tree, and the written file does not reappear on a hit.  See
  :doc:`file_semantics`.

See also
--------

* :doc:`file_semantics` — the same contract for files and directories.
* :doc:`helpers` — ``.rerun()`` for forcing a cold call deliberately.
