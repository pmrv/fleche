"""One-shot migration: convert integer ``version`` values to JSON-string form.

**When to run this:**

If you see the following error when loading from a SQL-backed fleche cache::

    TypeError: the JSON object must be str, bytes or bytearray, not int

your database was created before PR #396, which changed the ``version`` column
from a raw ``INTEGER`` to a JSON-encoded ``TEXT``.  Run this script once to
upgrade the existing rows.

**Usage (Python):**

    python scripts/migrate_sql_version_field.py path/to/your_cache.db

**Usage (sqlite3 CLI — one-liner):**

    sqlite3 path/to/your_cache.db \\
        "UPDATE calls SET version = CAST(version AS TEXT) \\
         WHERE version IS NOT NULL AND typeof(version) = 'integer';"

**What the migration does:**

Old rows stored the version as a raw SQLite INTEGER, e.g. the value ``1``.
New code writes ``json.dumps(version)``, so an integer ``1`` becomes the TEXT
string ``'1'``.  The migration converts every INTEGER-typed ``version`` cell to
its TEXT equivalent with a single UPDATE; TEXT cells (already migrated /
written by the new code) and NULL cells are untouched.

Only SQLite databases are handled here.  For PostgreSQL or MySQL the column
type change would require an ALTER TABLE plus a data UPDATE — consult your
DBA / dialect documentation.
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path


def migrate(db_path: str | Path) -> int:
    """Migrate integer ``version`` values to JSON-string form.

    Returns the number of rows updated.  Safe to run multiple times — rows
    already in TEXT form are skipped.
    """
    path = Path(db_path).expanduser().resolve()
    if not path.exists():
        raise FileNotFoundError(f"Database not found: {path}")

    with sqlite3.connect(path) as conn:
        cur = conn.execute(
            "UPDATE calls"
            " SET version = CAST(version AS TEXT)"
            " WHERE version IS NOT NULL AND typeof(version) = 'integer'"
        )
        conn.commit()
        return cur.rowcount


def main() -> None:
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(1)

    db_path = sys.argv[1]
    try:
        n = migrate(db_path)
    except FileNotFoundError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

    if n == 0:
        print("No rows needed migration (database is already up to date).")
    else:
        print(f"Migrated {n} row(s).  Database is now up to date.")


if __name__ == "__main__":
    main()
