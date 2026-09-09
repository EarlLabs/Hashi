"""The few things the owner does from a shell rather than the panel.

WHAT: ``hash-password`` (produce the value for ``HASHI_OPERATOR_PASSWORD_HASH``) and
      ``check-config`` (validate a rendered config with the upstream checker).
WHY:  the operator's password hash has to be generated somewhere, and it must not be
      an endpoint — an endpoint that hashes a password is an endpoint that receives
      passwords. A local command keeps the plaintext on the owner's own machine.
HOW:  ``python -m control.cli hash-password``. Reads the password from a prompt
      rather than from an argument, because a command-line argument is world-readable
      in ``/proc`` and lands in shell history.
"""

import argparse
import getpass
import pathlib
import sys

from control.app.crypto import hash_password
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

    args = parser.parse_args(argv)
    return int(args.handler(args))


if __name__ == "__main__":
    raise SystemExit(main())
