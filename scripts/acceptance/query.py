#!/usr/bin/env python3
"""hashi — the acceptance agent's read-only window into the stand's database.

WHAT: one ``SELECT`` against the disposable e2e stack, printed as rows an agent
      can paste into its report as evidence. ``--tables`` lists what it can see.

WHY:  without this, the finding class **works, but lies** cannot be told apart
      from **works**. The panel said the user was revoked and the row still
      carries the credential; the button said "applied" and the node's digest
      never moved — that last one is exactly M1 in ``docs/PLAN.md``, a bug whose
      whole failure mode was "the screen looked right". An acceptance agent with
      no database access can only believe the screen, which is the one thing that
      did not need checking.

WHY the parser, given the role already cannot write. Two locks, and the order
      matters. The real lock is the ROLE: ``acceptance_ro`` holds ``SELECT`` and
      nothing else, granted by ``stand.sh``, so an agent that talks itself into
      writing a row simply cannot. The parser is the second one, and it is what
      makes the refusal *legible* — a rejected statement says so here rather than
      arriving as a permission error from Postgres three steps into a run.

HOW:  ``scripts/acceptance/query.py "SELECT id, name FROM nodes"``
      ``scripts/acceptance/query.py --tables``

      Connection defaults match the Makefile's e2e block and are overridable for
      the same reason it documents: an engine that is not the machine you are
      sitting at.

NEVER point this at .env. It speaks to the throwaway stack only, whose whole
database is destroyed by ``stand.sh down``.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import pathlib
import re
import sys

# asyncpg is a runtime dependency of the control plane, so it is in .venv and not
# in the system interpreter. Re-exec rather than fail: this script is named as a
# bare command in aikit.yml, and an acceptance run should not be lost to which
# python happened to be first on PATH.
#
# The loop guard is an environment variable and NOT "am I already that binary?".
# A venv's `python` is a symlink to the base interpreter, so `sys.executable`
# and `.venv/bin/python` RESOLVE TO THE SAME PATH — a comparison of resolved
# paths is therefore always equal and never re-execs, which is exactly how this
# first shipped: every invocation reported "no .venv was found" while .venv sat
# right there.
_REEXEC = "HASHI_ACCEPTANCE_QUERY_REEXEC"
try:
    import asyncpg
except ModuleNotFoundError:  # pragma: no cover - exercised by running it
    _venv = pathlib.Path(__file__).resolve().parents[2] / ".venv" / "bin" / "python"
    if _venv.exists() and not os.environ.get(_REEXEC):
        os.execve(
            str(_venv),
            [str(_venv), *sys.argv],
            {**os.environ, _REEXEC: "1"},
        )
    raise SystemExit(
        f"asyncpg is not importable from {sys.executable} and "
        f"{_venv} could not supply it — run: make setup"
    ) from None


HOST = os.environ.get("E2E_DB_HOST", os.environ.get("E2E_API_HOST", "127.0.0.1"))
PORT = int(os.environ.get("E2E_DB_PORT", "54232"))
DATABASE = os.environ.get("ACCEPTANCE_DB_NAME", "hashi")
ROLE = os.environ.get("ACCEPTANCE_DB_ROLE", "acceptance_ro")
# The stand's own throwaway credential, mirroring stand.sh. Committed on the same
# grounds as deploy/e2e.env: it guards a stack with no real nodes and no real
# users in it. Nothing here may ever be copied into .env.
PASSWORD = os.environ.get("ACCEPTANCE_DB_PASSWORD", "acceptance-ro-not-a-real-password")

# Rejected as whole words, so a column named `updated_at` is not mistaken for an
# UPDATE. Belt to the role's braces — see the module docstring.
FORBIDDEN = re.compile(
    r"\b(insert|update|delete|drop|alter|create|grant|revoke|truncate|copy|"
    r"call|do|merge|refresh|vacuum|set|reset|begin|commit|rollback)\b",
    re.IGNORECASE,
)


class Rejected(ValueError):
    """The statement never reached the database. The message goes in the report."""


def check(sql: str) -> str:
    """Return the statement, or explain why it is not one read-only ``SELECT``."""
    statement = sql.strip().rstrip(";").strip()
    if not statement:
        raise Rejected("empty statement")
    if ";" in statement:
        # A trailing semicolon was already stripped, so anything left is a second
        # statement smuggled in behind the first.
        raise Rejected("more than one statement — this runs exactly one SELECT")
    if not statement[:6].lower() == "select":
        # WITH is refused deliberately, not overlooked: a Postgres CTE may contain
        # `INSERT ... RETURNING`, so "starts with WITH" is not a read-only test.
        raise Rejected("must begin with SELECT (WITH is refused: a CTE can carry a write)")
    found = FORBIDDEN.search(statement)
    if found:
        raise Rejected(f"contains a keyword that is not read-only: {found.group(0)!r}")
    return statement


TABLES = """
SELECT table_name
  FROM information_schema.table_privileges
 WHERE grantee = current_user AND privilege_type = 'SELECT'
 ORDER BY table_name
"""


def render(rows: list, columns: list[str]) -> str:
    """Rows as fixed-width columns — readable in a terminal and in a report."""
    if not rows:
        return "(0 rows)"
    table = [columns] + [[("" if v is None else str(v)) for v in r.values()] for r in rows]
    widths = [max(len(row[i]) for row in table) for i in range(len(columns))]
    line = "-+-".join("-" * w for w in widths)
    out = [" | ".join(c.ljust(w) for c, w in zip(table[0], widths, strict=True)), line]
    out += [
        " | ".join(c.ljust(w) for c, w in zip(row, widths, strict=True))
        for row in table[1:]
    ]
    out.append(f"({len(rows)} row{'s' if len(rows) != 1 else ''})")
    return "\n".join(out)


async def run(statement: str) -> int:
    try:
        conn = await asyncpg.connect(
            host=HOST, port=PORT, database=DATABASE, user=ROLE, password=PASSWORD
        )
    except OSError as exc:
        print(
            f"no database at {HOST}:{PORT} ({exc}) — is the stand up? "
            "scripts/acceptance/stand.sh up",
            file=sys.stderr,
        )
        return 2
    except asyncpg.PostgresError as exc:
        print(f"could not connect as {ROLE}: {exc}", file=sys.stderr)
        return 2
    try:
        rows = await conn.fetch(statement)
    except asyncpg.PostgresError as exc:
        print(f"postgres refused the query: {exc}", file=sys.stderr)
        return 1
    finally:
        await conn.close()
    columns = list(rows[0].keys()) if rows else []
    print(render(list(rows), columns))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="One read-only SELECT against the acceptance stand.",
    )
    parser.add_argument("sql", nargs="?", help="a single SELECT statement")
    parser.add_argument(
        "--tables", action="store_true", help="list the tables this role may read"
    )
    args = parser.parse_args()

    if args.tables:
        return asyncio.run(run(TABLES))
    if not args.sql:
        parser.error("give a SELECT statement, or --tables")
    try:
        statement = check(args.sql)
    except Rejected as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    return asyncio.run(run(statement))


if __name__ == "__main__":
    raise SystemExit(main())
