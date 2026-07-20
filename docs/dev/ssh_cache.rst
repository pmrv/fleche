.. _ssh-cache-internals:

``SshCache`` internals
======================

This page is a tour of :mod:`fleche.remote` for contributors hacking on the
cross-machine cache.  End-user documentation lives in
:doc:`/storage/configuration`; this page explains *how* the pieces fit
together.

Security model
--------------

The wire format is :mod:`cloudpickle` in **both directions**.  That has
two unavoidable consequences:

- A hostile **server** can run arbitrary code on the **client** by
  returning a crafted payload that the client's ``cloudpickle.loads``
  executes.
- A hostile **client** can run arbitrary code on the **server**
  symmetrically.

The trust boundary is therefore exactly the same as ``ssh user@host``
itself: SSH provides confidentiality and authentication of the
endpoints, and we trust both ends not to ship hostile pickled objects.
**Do not point** :class:`~fleche.remote.SshCache` **at a host you would
not** ``ssh`` **into**, and do not expose the server entry point
(``python -m fleche remote --serve``) on any transport other than the
spawned SSH stdin/stdout — there is no authentication on the RPC
stream itself.

Cloudpickle is the right call for this feature (we need to ship
arbitrary Python objects across, including user value types) but a
JSON / msgpack / protobuf wire format with a strict schema would have
removed this trust requirement at the cost of constraining the kind of
values fleche can cache. That trade-off was made deliberately; revisit
it if SshCache ever needs to support untrusted multi-tenant use.

Credentials in ``info()``
~~~~~~~~~~~~~~~~~~~~~~~~~

The ``info`` RPC ships
:func:`~fleche.config.cache_to_config` of the served cache back to the
client.  The raw config contains credentials —
:class:`~fleche.storage.pickle_file.PickleFileBackend` writes its HMAC
signing keys (``secret_key``) as hex strings, and the SQL backend's
``url`` may include a database password in the userinfo component.
:func:`fleche.remote._server_info` therefore walks the config through
:func:`fleche.remote._redact_config` before putting it on the wire:
``secret_key`` values are replaced with ``"<redacted>"`` and URL
passwords are masked to ``***``.  This matters because the client's
DEBUG-level RPC tracing logs the full response payload — without the
redactor, signing keys would land in any DEBUG log file by default.

If you add a new storage type that round-trips credentials through
``cache_to_config``, extend
:data:`fleche.remote._SENSITIVE_CONFIG_KEYS` to cover the new field
name.

Version handshake
~~~~~~~~~~~~~~~~~

The first cache operation on a fresh :class:`~fleche.remote.SshCache`
implicitly fetches an :ref:`info <ssh-cache-internals>` dict via
:meth:`fleche.remote.SshCache._ensure_handshake`, which calls
:func:`fleche.remote._warn_on_version_skew` on the response.  Mismatched
``fleche_version`` or ``cloudpickle_version`` between client and server
logs a ``WARNING`` on the ``fleche.remote`` logger — schema or wire
format drift is the most common root cause of silently-wrong records
across a fleche upgrade, and this surfaces it without forcing a hard
failure (forwards-compatible patch releases are common in practice and
the user has no recourse mid-session from a raise).

The handshake fires on the first BaseCache method on the SshCache,
even reads — every method calls ``_ensure_handshake()`` at its top.
Cost is exactly one extra RPC per session.

Goals and constraints
---------------------

The cross-machine cache exists to let two (or more) machines share results of
expensive ``@fleche()`` calls without copying their cache files around by
hand.  The constraints that shaped the design:

- **No always-on daemon.**  The remote side is a vanilla Python process
  spawned on demand by the client.  Nothing has to be running before the
  first cache lookup.
- **Single authentication.**  Most multi-user clusters require 2FA.  A
  client that silently reconnects whenever the connection drops would
  re-prompt the user, possibly while they are away.  Auto-reconnect is
  therefore explicitly out of scope (see *Lifecycle* below).
- **Backend agnosticism.**  The remote keeps full freedom over which
  :class:`~fleche.caches.BaseCache` it serves — including stacks
  containing further :class:`~fleche.remote.SshCache` instances, if a
  user really wants chained shares.
- **Cheap round-trips.**  Cache ops are typically tiny payloads
  (digest hits, ``contains`` probes).  The wire protocol favours
  per-call latency over fan-out.

Process and stream layout
-------------------------

One :class:`~fleche.remote.SshCache` owns exactly one
:class:`fleche.remote._SshConnection`, which in turn owns at most one
``Popen``:

.. code-block:: text

   client                                       remote
   ──────                                       ──────

   SshCache.<op>(...)            <op> ∈ save / load / load_value /
       │    ▲                            contains / expand / shrink /
   call│    │return                      query / evict / info
       ▼    │
   ┌──────────────────────┐                ┌─────────────────────┐
   │_SshConnection        │──(stdin) req──>│ python -m           │
   │                      │                │   fleche remote     │
   │ ssh host             │<─(stdout) resp─│   --serve           │
   │ python -m fleche     │                │                     │
   │ remote --serve       │<─(stderr) lines│   serve(...) loop   │
   └──────────────────────┘                └─────────────────────┘
       │
       │ stderr drained by a daemon thread
       ▼
   fleche.remote.host.<host>  +  50-line ring buffer

Three streams cross the SSH boundary:

* **stdin / stdout** carry length-prefixed cloudpickle RPC frames.  All
  cache operations multiplex over this single pair; there is no
  fan-out and no parallel requests.  ``_Connection.call`` takes a
  :class:`threading.Lock` for the entire write→read round-trip so
  threaded callers serialise naturally.
* **stderr** is drained by a daemon thread running
  :func:`fleche.remote._forward_stderr`.  Each line is logged at
  ``INFO`` on the per-host logger ``fleche.remote.host.<host>`` *and*
  appended to a 50-line ring buffer on the connection.  When the
  subprocess dies,
  :meth:`fleche.remote._SshConnection._diagnose` returns the buffered
  tail plus the exit code so
  :class:`~fleche.remote.RemoteConnectionError` carries the actual
  cause instead of just ``EOFError``.

  The logger name is constructed in
  :meth:`fleche.remote._SshConnection._open` from the SSH host string;
  dots become ``_`` and ``@`` becomes ``_at_`` so the host name doesn't
  fragment the logger hierarchy.  For example, ``user@bigpc.example.com``
  produces ``fleche.remote.host.user_at_bigpc_example_com``.  Because
  the name uses ``.`` as the separator, each host's logger is a real
  child of ``fleche.remote`` and standard logger configuration
  propagates: setting
  ``logging.getLogger("fleche.remote").setLevel(...)`` controls every
  per-host child, while
  ``logging.getLogger("fleche.remote.host.user_at_bigpc_example_com")``
  lets you raise or silence one host independently.

Wire protocol
-------------

Every frame is a 4-byte big-endian length prefix (``struct.Struct(">I")``)
followed by a cloudpickle payload.  See :func:`fleche.remote._write_frame`
and :func:`fleche.remote._read_frame`.

Requests are 3-tuples ``(method: str, args: tuple, kwargs: dict)``;
responses are 2-tuples either ``("ok", value)`` or ``("err", exception)``.
Exceptions re-raise on the client side, so a server-side
:exc:`KeyError` becomes a :exc:`KeyError` to the caller, a
:exc:`~fleche.caches.Rejected` stays a :exc:`~fleche.caches.Rejected`,
and so on.

If the exception itself can't be cloudpickled (some C-extension types
refuse), the server downgrades it to a :exc:`RuntimeError` carrying the
formatted traceback so the client at least sees what went wrong.

Server-side dispatch
~~~~~~~~~~~~~~~~~~~~

:func:`fleche.remote._dispatch` is a single dict lookup into
``_REMOTE_METHODS`` — one entry per :class:`~fleche.caches.BaseCache`
method, plus ``info`` handled at the :func:`~fleche.remote.serve` level.
The explicit table is deliberate: it documents the full API surface, gives
any future method addition a clear place to wire up server-side
translation, and avoids giving remote callers reflective access to
arbitrary attributes of the cache.

Two pieces need server-side translation rather than raw passthrough:

- :meth:`~fleche.caches.BaseCache.load` and
  :meth:`~fleche.caches.BaseCache._query` produce
  :class:`~fleche.call.LazyCall` instances whose ``_cache`` field
  points at the *server's* cache.  That pointer cannot travel across
  the wire (it would reach back into a different process on
  deserialisation).  :func:`fleche.remote._strip_cache` strips it and
  returns a plain :class:`~fleche.call.DigestedCall`; the client then
  calls ``DigestedCall.fetch(self)`` to re-bind it to the local
  :class:`~fleche.remote.SshCache`.  Subsequent ``.result`` accesses
  on the lazy call therefore round-trip through ``load_value`` on the
  client's SshCache and back to the remote — fetching the value only
  when actually used.
- :meth:`~fleche.caches.BaseCache.query` is a generator on the server
  side.  ``_dispatch`` materialises the whole iterator into a tuple
  before sending it back, because the wire protocol is request /
  response, not streaming.  Large query results pay the cost up front
  in one frame.

Client side
~~~~~~~~~~~

:meth:`fleche.remote._Connection.call` is the one entry point for every
RPC.  It acquires the lock, lazily opens the connection if needed,
writes the request frame, reads exactly one response frame, and
dispatches on the response tag.  On
``(BrokenPipeError, EOFError, OSError)`` it calls ``_diagnose()`` to
collect transport-specific detail, closes the connection, and raises
:class:`~fleche.remote.RemoteConnectionError`.

A note on logging: every RPC is logged at ``DEBUG`` on the
``fleche.remote`` logger as ``rpc → method args=...`` and ``rpc ←
method ok``.  Enabling debug-level logging on that namespace gives a
complete trace of the wire traffic without instrumenting any code.

Lifecycle
---------

The subprocess is spawned lazily on the first cache operation.  Once
opened it lives for the lifetime of the Python process and is closed
via :py:mod:`atexit` (the client's hook is registered on first
``_open``).

.. note:: **Subprocesses are not closed on garbage collection.**

   ``atexit.register(self.close)`` keeps a reference to the connection
   alive for the whole process, so a :class:`~fleche.remote.SshCache`
   that goes out of scope is *not* eligible for collection and its SSH
   subprocess stays up until interpreter exit.  In a long-running
   interactive session that creates and discards many ``SshCache``
   instances (e.g. repeatedly re-reading a config), the subprocesses
   accumulate.  Call :meth:`~fleche.remote.SshCache.close` explicitly
   when done with a cache you won't reuse.  A future revision could use
   a ``weakref``-based atexit hook so dropped caches clean themselves
   up, but the simple always-on-exit cleanup is correct for the common
   case of a handful of long-lived caches.

.. note:: **Reading** ``info()`` / ``read_only`` **costs an RPC.**

   :meth:`~fleche.remote.SshCache.info` and the
   :attr:`~fleche.remote.SshCache.read_only` property are not free: the
   first access fetches the server info dict over the wire (and drives
   the version handshake).  The result is cached for the lifetime of
   the connection, so only the first access pays; but a user poking
   ``sc.read_only`` in a REPL should know it is a network round-trip,
   not a local attribute.  :meth:`~fleche.remote.SshCache.reconnect`
   invalidates the cache, so the next access re-fetches.

There is no automatic reconnect.  If the SSH subprocess dies — network
hiccup, server reboot, idle timeout — every subsequent op raises
:class:`~fleche.remote.RemoteConnectionError` until the caller invokes
:meth:`~fleche.remote.SshCache.reconnect` explicitly.  The error
message produced in
:meth:`fleche.remote._Connection.call` names ``SshCache.reconnect()``
directly so the user doesn't have to know about the lifecycle helper
ahead of time.  This is the single most opinionated decision in the
module: an auto-reconnect would silently re-trigger interactive 2FA
prompts (often while the user is away from the terminal).  Forcing the
call to be explicit means the user can decide *when* to pay that cost.

For sessions that span multiple Python runs, the recommended pattern is
OpenSSH ``ControlMaster`` + ``ControlPersist``: the first connection
authenticates and the multiplexer keeps the underlying TCP session
alive across child processes, so subsequent ``ssh`` invocations within
the persist window skip the handshake entirely.  Wire it up either in
``~/.ssh/config`` or via the ``ssh_options`` field on
:class:`~fleche.remote.SshCache` (see the docstring for an example).

Setup-commands chain
~~~~~~~~~~~~~~~~~~~~

When the user passes ``workdir`` and/or ``setup_commands``, the
constructed remote command looks like:

.. code-block:: text

   cd <workdir> && <snippet1> && <snippet2> && ... && exec <python> -m fleche remote --serve

The trailing ``exec`` replaces the wrapping shell so stdin/stdout pipe
straight through to the server process — no extra layer to corrupt the
binary RPC stream.  Any setup failure short-circuits via ``&&`` and the
ssh process exits non-zero; the client's next read raises ``EOFError``
and the diagnostic captured from stderr surfaces the actual reason.

``workdir`` (when set) contributes the leading ``cd`` so it runs ahead
of the user's ``setup_commands``.  Because the server boots the cache
via ``python -m``, that working directory lands on ``sys.path``, letting
the remote import the project-local modules referenced by unpickled
calls.

Without ``workdir`` or ``setup_commands``, the server argv is passed
directly to ``ssh`` as separate arguments, so SSH ``exec``\\ s it as-is
— no remote shell is involved at all.

Diagnostics: the ``info`` RPC
-----------------------------

:func:`fleche.remote._server_info` is the introspection back-channel.
It is the only method dispatched at the :func:`~fleche.remote.serve`
level (alongside the data plane in :func:`~fleche.remote._dispatch`),
because it needs access to ``cache_name`` — the ``--cache`` argument
the server was launched with — which is not passed into
:func:`~fleche.remote._dispatch`.

It returns:

======================== =================================================
Key                      Meaning
======================== =================================================
``cache``                :func:`~fleche.config.cache_to_config` of the
                         served cache — a structured dict (or list, for
                         stacks) that round-trips back through
                         :func:`~fleche.config.cache_from_config`.
``cache_name``           The ``--cache`` argument the server was launched
                         with, or ``None`` for the default cache.
``read_only``            ``True`` when the served cache (or, for a
                         :class:`~fleche.caches.CacheStack`, its
                         ``stack[0]``) is a
                         :class:`~fleche.caches.ReadOnlyMixin`.
``cwd``                  ``os.getcwd()`` on the remote.
``hostname``             ``socket.gethostname()`` on the remote.
``python``               ``sys.executable`` on the remote.
``pid``                  The server process's PID.
``fleche_version``       The server's ``fleche`` package version string.
                         Compared against the client's version by
                         :func:`~fleche.remote._warn_on_version_skew`.
``cloudpickle_version``  The server's ``cloudpickle`` version string.
                         A mismatch with the client can cause silent
                         wire-format incompatibilities.
======================== =================================================

``info()`` is the debugging back-channel for any "the remote isn't
doing what I expected" question — wrong cache loaded, wrong working
directory, unexpected ``read_only`` flag, surprising Python
interpreter, surprising host.  Calling it from the client surfaces the
remote's view of itself in one round-trip, with no need to
``ssh host`` separately and poke around.

Active cache on the remote
~~~~~~~~~~~~~~~~~~~~~~~~~~

The server's served cache *is* its active cache.  ``python -m
fleche remote --serve`` installs the named cache on the
``fleche.state._CACHE`` ContextVar before entering the request loop,
so any code path on the remote that consults ``fleche.cache()``
independently — metadata hooks, ``LazyCall._cache`` references, nested
``@fleche()`` calls — sees the same instance the RPC layer is
dispatching against.  The server process is single-threaded and
serves exactly one cache, so there's no other sensible default.

Read-only short-circuit
~~~~~~~~~~~~~~~~~~~~~~~

:meth:`~fleche.remote.SshCache.save` and
:meth:`~fleche.remote.SshCache.evict` check the cached ``read_only``
flag from the server info dict before issuing the RPC.  If the flag is
``True`` they raise :class:`~fleche.caches.Rejected` locally with no
round-trip.

The flag is populated lazily — the first time ``read_only`` (or
``info()``) is consulted, an ``info`` RPC fires and the result is
cached on the :class:`~fleche.remote.SshCache` instance.  Subsequent
saves consult the cache directly.  Cost is therefore at most one
extra round-trip per session, and zero in the common case where the
first cache op is itself a write.

:meth:`~fleche.remote.SshCache.reconnect` invalidates the cached info
so the next read re-fetches against the new subprocess.

Testing strategy
----------------

The module ships two layers of tests, both in ``tests/{unit,integration}/test_remote.py``:

- **Unit tests** drive :func:`~fleche.remote.serve` in a background
  daemon thread with two ``os.pipe()`` pairs in place of an SSH
  subprocess.  The same wire-protocol machinery is exercised — frame
  layout, dispatch, exception propagation, the
  :class:`~fleche.remote._Connection` lifecycle — without SSH or
  process spawning.  Tests that need the *transport*'s behaviour
  (subprocess exit codes, stderr capture) drive a
  :class:`fleche.remote._Connection` subclass directly with no server
  on the other side; see ``test_connection_drop_includes_diagnose_output``.

- **Integration tests** launch ``python -m fleche remote --serve`` as
  a local subprocess (still no SSH involved) so the full
  ``Popen``-with-three-pipes handshake, module loading, and config-file
  parsing on the server side are all exercised.  Each test uses a
  ``tmp_path``-scoped ``fleche.toml`` so server state lives in an
  isolated directory.

Adding a new RPC
----------------

The path is short and entirely mechanical:

1. Add a ``_RemoteMethod`` entry to ``_REMOTE_METHODS`` in
   :mod:`fleche.remote` (or, if the RPC needs server-only state like
   ``cache_name``, handle it in :func:`~fleche.remote.serve` itself
   the way ``info`` does).  Be explicit about translating any
   cache-bound return value via :func:`~fleche.remote._strip_cache`.
2. Add a ``_ClientMethod`` entry to ``_CLIENT_METHODS``, setting
   ``write``, ``unwrap``, and ``reject_message`` as needed.  Then add a
   one-line method body on :class:`~fleche.remote.SshCache` that calls
   ``self._rpc("method_name", *args)``.  If the response carries
   :class:`~fleche.call.DigestedCall` instances, pass an ``unwrap``
   callable that calls ``.fetch(self)`` to re-bind them as client-side
   :class:`~fleche.call.LazyCall`\\ s.
3. Add tests at both layers: a unit test that drives the new method
   through the in-process pipe, and (when it's worth it) an
   integration test that exercises it across the subprocess boundary.

Avoid adding more methods than necessary — every new method is wire
surface that has to round-trip from any user.  Prefer threading the
new operation through one of the existing methods where possible.
