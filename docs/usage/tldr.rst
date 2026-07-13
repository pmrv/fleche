TL;DR
=====

Decorate a function; calls with the same arguments are computed once and
served from the cache afterwards:

.. code-block:: python

   from fleche import fleche

   @fleche()
   def expensive(x, y):
       print(f"computing {x} + {y}")
       return x + y

   expensive(1, 2)   # computes, caches
   expensive(1, 2)   # cache hit — nothing printed
   expensive(2, 3)   # new arguments, computes again

To persist results across runs, put a ``fleche.toml`` in your project
directory (or anywhere up to ``$HOME``):

.. code-block:: toml

   [default]
   cache = "persistent"

   [persistent]
   values.type = "pickle"
   values.root = "~/.cache/fleche/values"
   calls.type = "pickle"
   calls.root = "~/.cache/fleche/calls"

Without a config file, results are cached in memory for the current process
only.

The essentials beyond that:

.. code-block:: python

   from fleche import cache

   cache("persistent")         # switch the active cache by config name
   cache("void")               # turn caching off without touching code

   expensive.contains(1, 2)    # is this call cached?
   expensive.load(1, 2)        # fetch a result without executing (KeyError on miss)
   expensive.rerun(1, 2)       # force re-execution and overwrite the entry
   expensive.query().table()   # all stored calls as a pandas DataFrame

That is all you need for everyday use.  The rest of this section covers the
helper methods in depth (:doc:`helpers`), lazy loading of large cached
objects (:doc:`lazy_call`), and querying stored calls (:doc:`query`);
storage backends and configuration details live under
:doc:`/storage/configuration`.
