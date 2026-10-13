"""The few things the owner does from a shell rather than the panel.

WHAT: ``hash-password`` (produce the value for ``HASHI_OPERATOR_PASSWORD_HASH``),
      ``check-config`` (validate a rendered config with the upstream checker), and —
      since M36 — the three node commands a host rebuild needs: ``node-plan`` (what a
      fresh host must be prepared with for one node), ``relocate-node`` (point the
      record at that host) and ``apply-node`` (push and verify it).
WHY:  the operator's password hash has to be generated somewhere, and it must not be
      an endpoint — an endpoint that hashes a password is an endpoint that receives
      passwords. A local command keeps the plaintext on the owner's own machine.

      The node commands exist so that rebuilding a lost host is a script rather than a
      browser session. They run INSIDE the control container (``make node-plan`` and
      its neighbours wrap ``docker compose exec``), where the database and
      HASHI_SECRET_KEY already are — so they need no operator password, and whoever can
      run them already holds the shell that holds the database. Rejected: driving the
      API with a cookie jar from the script, which needs the operator password on the
      command line of a rebuild and is what the 2026-10-13 restore had to do by hand.
HOW:  ``python -m control.cli hash-password``. Reads the password from a prompt
      rather than from an argument, because a command-line argument is world-readable
      in ``/proc`` and lands in shell history. The node commands print ``key=value``
      lines (one value per line, never containing a newline) so a shell script can read
      them without a JSON parser and without ``eval``.
"""

import argparse
import asyncio
import contextlib
import getpass
import pathlib
import sys

from control.app.crypto import SecretBox, SecretUnreadable, hash_password
from control.app.errors import DomainError
from edge import checker


def escaped_for_env_file(value: str) -> str:
    """A value that survives being read out of an env file by docker compose.

    WHY THIS IS DECIDED HERE. A scrypt hash is ``scrypt$n$r$p$salt$digest`` and
    ``docker compose --env-file`` — which every invocation in this project uses,
    because CLAUDE.md requires it — expands the values it reads. So ``$digest``
    becomes a variable reference and the digest arrives empty, unless the digest
    happens to start with a digit. Roughly five deployments in six are damaged, and
    the damage is silent: compose exits 0, the health check passes, and the operator
    is locked out of their own panel with a 401.

    Three places could fix it and only one of them is honest. Telling the operator to
    double the dollars is the version that was already tried — it is in the runbook —
    and it is a rule a person copying a hash at three in the morning does not follow.
    Having the bootstrap script rewrite their env file means a script editing the file
    that holds their secrets, to a value they did not choose. That leaves the command
    that prints the value: it knows exactly where the value is going, it is the only
    step the operator cannot skip, and pre-escaping costs the reader nothing but a
    sentence of explanation.

    The one case this makes worse is the operator who exports the variable by hand
    instead of using compose: they get a hash with doubled dollars and no expansion.
    That is why ``Settings`` refuses to boot on a malformed hash and names this exact
    case in its message — a loud failure at boot rather than a quiet 401 forever.
    """
    return value.replace("$", "$$")


def command_hash_password(_args: argparse.Namespace) -> int:
    """Prompt for a password twice and print its hash."""
    password = getpass.getpass("operator password: ")
    if len(password) < 12:
        # Not arbitrary: this single credential guards the panel that can read every
        # node's key, and there is no lockout (a deliberate decision — see
        # control/app/auth.py), so length is the whole defence.
        print("refusing: use at least 12 characters", file=sys.stderr)
        return 2
    if password != getpass.getpass("again: "):
        print("refusing: the two entries differ", file=sys.stderr)
        return 2

    print()
    print("Put this in .env (the hash, never the password), exactly as printed:")
    print(f"HASHI_OPERATOR_PASSWORD_HASH={escaped_for_env_file(hash_password(password))}")
    print()
    print("The doubled $$ are deliberate and belong in the file. docker compose")
    print("expands the values it reads from an env file, so it turns each $$ back")
    print("into one $ on the way to the container; a single $ there would start a")
    print("variable reference and the rest of that field would arrive empty.")
    return 0


def command_check_config(args: argparse.Namespace) -> int:
    """Validate a rendered config file with the upstream checker."""
    path = pathlib.Path(args.path)
    if not path.is_file():
        print(f"no such file: {path}", file=sys.stderr)
        return 2

    result = checker.validate(path.read_text())
    if not result.available:
        print(
            "no upstream checker installed, so nothing was verified. "
            "Install it: scripts/fetch-upstream-checkers.sh",
            file=sys.stderr,
        )
        return 3
    if not result.ok:
        print(result.output, file=sys.stderr)
        return 1
    print("the daemon accepts this configuration")
    return 0


# --- the node commands, M36 -------------------------------------------------------
#
# Imported inside the functions, not at the top: ``hash-password`` runs on a laptop that
# has no database and no HASHI_SECRET_KEY, and importing the settings module there would
# make a command that needs neither fail at import.

WRONG_KEY = (
    "a stored secret could not be decrypted: HASHI_SECRET_KEY on this host is not the key "
    "this database was written under. The data is intact; the key is wrong. Nothing has "
    "been changed."
)


async def _in_a_session(work):
    """Run ``work(session, settings)`` against this control plane's own database."""
    from control.app.db import Database  # noqa: PLC0415
    from control.app.main import configure_logging  # noqa: PLC0415
    from control.app.models.base import bind_secret_box  # noqa: PLC0415
    from control.app.services import apply  # noqa: PLC0415
    from control.app.settings import Settings  # noqa: PLC0415

    # The application's own logging setup, not a default one: it is what keeps asyncssh
    # and SQLAlchemy at WARNING, and an apply from a shell dials the same hosts with the
    # same libraries as one from the panel.
    configure_logging()
    settings = Settings()
    bind_secret_box(SecretBox(settings.secret_key))
    apply.bind_settings(settings)
    database = Database(settings.database_url)
    try:
        async with contextlib.aclosing(database.session()) as sessions:
            async for session in sessions:
                return await work(session, settings)
    finally:
        await database.dispose()


def _run(work) -> int:
    """The node commands' one error contract: a sentence on stderr and exit 1."""
    try:
        return int(asyncio.run(_in_a_session(work)))
    except DomainError as refused:
        print(refused.message, file=sys.stderr)
        return 1
    except SecretUnreadable:
        print(WRONG_KEY, file=sys.stderr)
        return 1


def _say(**values: object) -> None:
    """``key=value`` lines. A value carrying a newline would break the reader, so none may."""
    for key, value in values.items():
        text = "" if value is None else str(value)
        if "\n" in text or "\r" in text:
            raise DomainError(f"{key} holds a line break and cannot be printed as one line")
        print(f"{key}={text}")


def command_node_plan(args: argparse.Namespace) -> int:
    """What a fresh host needs for one node: the record's coordinates, key and ports."""

    async def work(session, settings):
        from control.app.services import relocation  # noqa: PLC0415

        node = await relocation.node_by_name(session, args.name)
        plan = await relocation.host_plan(session, node, settings)
        _say(
            name=node.name,
            state=node.state,
            address=node.address,
            ssh_host=node.ssh_host,
            ssh_user=node.ssh_user,
            ssh_port=node.ssh_port,
            host_key_pinned="yes" if node.ssh_host_key else "no",
            public_key=plan.public_key,
            ports=" ".join(plan.ports),
        )
        return 0

    return _run(work)


def command_relocate_node(args: argparse.Namespace) -> int:
    """Point a node record at a new host, through the audited service."""

    async def work(session, _settings):
        from control.app.services import nodes, relocation  # noqa: PLC0415

        node = await relocation.node_by_name(session, args.name)
        moved = await relocation.relocate_node(
            session,
            node_id=node.id,
            ssh_host=args.ssh_host,
            ssh_user=args.ssh_user,
            ssh_port=args.ssh_port,
            address=args.address,
            host_key=args.host_key,
        )
        names = [(await nodes.get_node(session, node_id)).name for node_id in moved.needs_apply]
        _say(changed="yes" if moved.changed else "no", needs_apply=" ".join(names))
        return 0

    return _run(work)


def command_apply_node(args: argparse.Namespace) -> int:
    """Render, push and verify one node — the panel's Apply button, from a shell."""

    async def work(session, _settings):
        from control.app.services import apply, relocation  # noqa: PLC0415

        node = await relocation.node_by_name(session, args.name)
        applied = await apply.apply_node(session, node_id=node.id)
        await session.refresh(node, ["state"])
        _say(
            applied=" ".join(sorted(applied.configs)),
            state=node.state,
            serving_unmeasured=" ".join(applied.unmeasured),
            serving_port_only=" ".join(applied.port_only),
            restarted_to_serve=" ".join(applied.restarted),
        )
        return 0

    return _run(work)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="control", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    hash_parser = commands.add_parser(
        "hash-password", help="generate HASHI_OPERATOR_PASSWORD_HASH"
    )
    hash_parser.set_defaults(handler=command_hash_password)

    check_parser = commands.add_parser(
        "check-config", help="validate a rendered node config with the upstream checker"
    )
    check_parser.add_argument("path")
    check_parser.set_defaults(handler=command_check_config)

    plan_parser = commands.add_parser(
        "node-plan", help="what a fresh host needs before this node is applied onto it"
    )
    plan_parser.add_argument("name")
    plan_parser.set_defaults(handler=command_node_plan)

    relocate_parser = commands.add_parser(
        "relocate-node", help="point a node record at the host that replaced its old one"
    )
    relocate_parser.add_argument("name")
    relocate_parser.add_argument("--ssh-host", required=True)
    relocate_parser.add_argument("--ssh-user", required=True)
    relocate_parser.add_argument("--ssh-port", required=True, type=int)
    relocate_parser.add_argument("--address", default=None)
    relocate_parser.add_argument(
        "--host-key", default=None, help="the new host's public host key, one line"
    )
    relocate_parser.set_defaults(handler=command_relocate_node)

    apply_parser = commands.add_parser("apply-node", help="render, push and verify one node")
    apply_parser.add_argument("name")
    apply_parser.set_defaults(handler=command_apply_node)

    args = parser.parse_args(argv)
    return int(args.handler(args))


if __name__ == "__main__":
    raise SystemExit(main())
