"""``python -m fleche <command> ...`` dispatcher.

Currently the only subcommand is ``remote``, which runs the cache RPC
server :class:`fleche.remote.SshCache` connects to.  Register additional
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
    return parser


def _main(argv: list[str]) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.command == "remote":
        if not args.serve:
            parser.error("nothing to do; pass --serve to run the cache server")
        from .remote import _run_server

        return _run_server(cache_name=args.cache)
    parser.error(f"unknown command: {args.command!r}")
    return 2


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
