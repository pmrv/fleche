"""``python -m fleche <command> ...`` dispatcher.

Subcommands: ``remote`` runs the cache RPC server
:class:`fleche.remote.SshCache` connects to; ``db`` hosts a local
PostgreSQL/MariaDB server for the ``sql`` calls backend
(:mod:`fleche.dbserver`).  Register additional
subcommands by adding a parser in :func:`_build_parser` and a branch in
:func:`_main`.

The CLI deliberately lives here rather than inside ``fleche.remote``:
the package's ``__init__`` transitively imports ``fleche.remote`` (e.g.
through :mod:`fleche.config`), so invoking the server as
``python -m fleche.remote`` would load ``remote.py`` twice — once as the
submodule and once as ``__main__`` — and emit the ``runpy`` "found in
sys.modules ... prior to execution" warning, with two separate copies of
every class and exception in the file.  ``__main__.py`` is never imported
as a submodule, so routing through it avoids the duplicate.
"""

import argparse
import sys


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m fleche")
    sub = parser.add_subparsers(dest="command", required=True)

    remote = sub.add_parser(
        "remote",
        help="run the remote cache RPC server (used by SshCache)",
    )
    remote.add_argument(
        "--serve",
        action="store_true",
        help="run the cache server reading RPC frames from stdin",
    )
    remote.add_argument(
        "--cache",
        default=None,
        help="named cache from the local fleche.toml (default: the file's default)",
    )

    db = sub.add_parser(
        "db",
        help="host a local PostgreSQL/MariaDB server for the sql calls backend",
    )
    db.add_argument(
        "backend",
        choices=["postgres", "mariadb", "stop"],
        help="server to run, or stop the one running for DATADIR",
    )
    db.add_argument("datadir", help="data directory; initialized on first use")
    db.add_argument(
        "--host",
        default="127.0.0.1",
        help="address to listen on (default: 127.0.0.1; 0.0.0.0 for other nodes)",
    )
    db.add_argument(
        "--port", type=int, default=None, help="port (default: last used, else a free one)"
    )
    db.add_argument(
        "--cache",
        default=None,
        metavar="NAME",
        help="record the server in fleche.toml as cache NAME: update the file declaring "
        "it, or add it to ./fleche.toml with the active cache's value storage",
    )
    db.add_argument(
        "--bindir",
        default=None,
        help="directory holding the server binaries (default: search PATH)",
    )
    return parser


def _main(argv: list[str]) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.command == "remote":
        if not args.serve:
            parser.error("nothing to do; pass --serve to run the cache server")
        from .remote import _run_server

        return _run_server(cache_name=args.cache)
    if args.command == "db":
        from .dbserver import DbServerError, serve, stop

        try:
            if args.backend == "stop":
                return stop(args.datadir)
            return serve(
                args.backend,
                args.datadir,
                host=args.host,
                port=args.port,
                bindir=args.bindir,
                cache=args.cache,
            )
        except DbServerError as e:
            print(f"error: {e}", file=sys.stderr)
            return 1
    parser.error(f"unknown command: {args.command!r}")
    return 2


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
